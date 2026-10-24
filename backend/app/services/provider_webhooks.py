"""Provider-side webhook registration adapters.

Only providers with a documented webhook-management API are supported here.
Slack's Events API is configured in the Slack app dashboard and is therefore
explicitly unsupported for automatic registration.

GitLab registration is exercised only against mocked HTTP clients in the test
suite; it has not been verified against a live GitLab instance.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("provider_webhooks")

PROVIDER_BY_NODE = {
    "github_trigger": "github",
    "stripe_trigger": "stripe",
    "shopify_trigger": "shopify",
    "slack_trigger": "slack",
    "typeform_trigger": "typeform",
    "gitlab_trigger": "gitlab",
}
SUPPORTED_PROVIDERS = frozenset(PROVIDER_BY_NODE.values())
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
GITLAB_PROJECT_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$")
TYPEFORM_FORM_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TYPEFORM_TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
GITLAB_EVENT_FLAGS = {
    "push": "push_events",
    "merge_request": "merge_requests_events",
    "merge_requests": "merge_requests_events",
    "merge_request_events": "merge_requests_events",
    "merge_requests_events": "merge_requests_events",
    "tag_push": "tag_push_events",
    "tag_push_events": "tag_push_events",
}
GITLAB_EVENT_DEFAULTS = {
    "push_events": True,
    "merge_requests_events": True,
    "tag_push_events": False,
}


class ProviderWebhookError(ValueError):
    """A provider webhook API rejected or could not complete a request."""


@dataclass(frozen=True)
class ProviderRegistrationResult:
    external_id: str
    signing_secret: str | None
    provider_config: dict[str, Any]


MAX_PROVIDER_EVENTS = 50
MAX_PROVIDER_EVENT_LENGTH = 256


def _string_list(value: Any, name: str, *, default: list[str]) -> list[str]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ProviderWebhookError(f"{name} must be a list of non-empty strings.")
    if len(value) > MAX_PROVIDER_EVENTS:
        raise ProviderWebhookError(
            f"{name} may contain at most {MAX_PROVIDER_EVENTS} items."
        )
    items = [item.strip() for item in value]
    if any(len(item) > MAX_PROVIDER_EVENT_LENGTH for item in items):
        raise ProviderWebhookError(
            f"{name} items may contain at most {MAX_PROVIDER_EVENT_LENGTH} characters."
        )
    return items or default


def _gitlab_project(config: dict[str, Any]) -> str:
    project = str(config.get("project") or "").strip()
    parts = project.split("/")
    if (
        not GITLAB_PROJECT_RE.fullmatch(project)
        or any(part in (".", "..") for part in parts)
    ):
        raise ProviderWebhookError("GitLab project must be in group/project form.")
    return project


def _config_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off"):
            return False
    raise ProviderWebhookError(f"{name} must be a boolean.")


def _gitlab_event_flags(config: dict[str, Any]) -> dict[str, bool]:
    flags = dict(GITLAB_EVENT_DEFAULTS)
    events = config.get("events")
    if events is not None:
        selected = (
            [item.strip() for item in events.split(",") if item.strip()]
            if isinstance(events, str)
            else _string_list(events, "events", default=[])
        )
        flags = {key: False for key in flags}
        for event in selected:
            flag = GITLAB_EVENT_FLAGS.get(event.strip().lower())
            if flag is None:
                raise ProviderWebhookError(
                    "GitLab events must be one of: push, merge_request, tag_push."
                )
            flags[flag] = True
    for key in flags:
        value = config.get(key)
        if value is not None:
            flags[key] = _config_bool(value, key)
    return flags


def _response_error(provider: str, response: Any) -> ProviderWebhookError:
    status_code = getattr(response, "status_code", "?")
    # Provider error bodies frequently contain project/form names and other
    # tenant metadata.  Keep them out of API responses and persisted errors;
    # the status code is enough for the UI to guide the user.
    logger.warning("%s webhook API returned HTTP %s", provider, status_code)
    return ProviderWebhookError(
        f"{provider} webhook API returned HTTP {status_code}. "
        "Verify the provider configuration and try again."
    )


def _json(response: Any, provider: str) -> dict[str, Any]:
    if getattr(response, "status_code", 0) >= 400:
        raise _response_error(provider, response)
    try:
        data = response.json()
    except Exception as exc:
        raise ProviderWebhookError(f"{provider} returned a non-JSON response.") from exc
    if not isinstance(data, dict):
        raise ProviderWebhookError(f"{provider} returned an unexpected response.")
    return data


async def register_provider_webhook(
    *,
    provider: str,
    credential: dict[str, Any],
    callback_url: str,
    config: dict[str, Any],
    signing_secret: str | None,
) -> ProviderRegistrationResult:
    from app.security.safe_http_client import get_safe_http_client

    if provider not in SUPPORTED_PROVIDERS:
        if provider == "slack":
            raise ProviderWebhookError(
                "Slack Events API registration must be configured in the Slack app dashboard; "
                "automatic provider registration is not supported."
            )
        raise ProviderWebhookError(f"Automatic webhook registration is not supported for {provider}.")

    async with get_safe_http_client() as client:
        if provider == "github":
            token = str(credential.get("access_token") or "").strip()
            if not token:
                raise ProviderWebhookError("GitHub credential requires access_token.")
            repo = str(config.get("repository") or "").strip()
            if not GITHUB_REPO_RE.fullmatch(repo):
                raise ProviderWebhookError("GitHub repository must be in owner/repo form.")
            events = _string_list(config.get("events"), "events", default=["push"])
            secret = signing_secret
            if not secret:
                raise ProviderWebhookError("GitHub registration requires a webhook secret.")
            response = await client.post(
                f"https://api.github.com/repos/{repo}/hooks",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "name": "web",
                    "active": True,
                    "events": events,
                    "config": {
                        "url": callback_url,
                        "content_type": "json",
                        "secret": secret,
                    },
                },
                timeout=30.0,
            )
            data = _json(response, "GitHub")
            if data.get("id") is None:
                raise ProviderWebhookError("GitHub did not return a webhook id.")
            return ProviderRegistrationResult(
                external_id=str(data["id"]),
                signing_secret=secret,
                provider_config={"repository": repo, "events": events},
            )

        if provider == "gitlab":
            token = str(credential.get("access_token") or "").strip()
            if not token:
                raise ProviderWebhookError("GitLab credential requires access_token.")
            project = _gitlab_project(config)
            base = str(credential.get("host") or "https://gitlab.com").strip().rstrip("/")
            if not base.startswith("https://"):
                raise ProviderWebhookError("GitLab credential host must use HTTPS.")
            secret = signing_secret
            if not secret:
                raise ProviderWebhookError("GitLab registration requires a webhook token.")
            event_flags = _gitlab_event_flags(config)
            response = await client.post(
                f"{base}/api/v4/projects/{quote(project, safe='')}/hooks",
                headers={"PRIVATE-TOKEN": token},
                json={
                    "url": callback_url,
                    "token": secret,
                    **event_flags,
                },
                timeout=30.0,
            )
            data = _json(response, "GitLab")
            if data.get("id") is None:
                raise ProviderWebhookError("GitLab did not return a webhook id.")
            return ProviderRegistrationResult(
                external_id=str(data["id"]),
                signing_secret=secret,
                provider_config={"project": project, **event_flags},
            )

        if provider == "stripe":
            key = str(credential.get("secret_key") or "").strip()
            if not key:
                raise ProviderWebhookError("Stripe credential requires secret_key.")
            events = _string_list(
                config.get("events"), "events", default=["payment_intent.succeeded"]
            )
            fields: list[tuple[str, str]] = [
                ("url", callback_url),
                ("description", "Flowsmith workflow webhook"),
            ]
            fields.extend(("enabled_events[]", event) for event in events)
            response = await client.request(
                "POST",
                "https://api.stripe.com/v1/webhook_endpoints",
                headers={"Authorization": f"Bearer {key}"},
                data=fields,
                timeout=30.0,
            )
            data = _json(response, "Stripe")
            external_id = data.get("id")
            secret = data.get("secret")
            if not external_id or not secret:
                raise ProviderWebhookError("Stripe did not return a webhook id and signing secret.")
            return ProviderRegistrationResult(
                external_id=str(external_id),
                signing_secret=str(secret),
                provider_config={"events": events},
            )

        if provider == "shopify":
            domain = str(credential.get("shop_domain") or "").strip().lower()
            token = str(credential.get("access_token") or "").strip()
            if not SHOP_DOMAIN_RE.fullmatch(domain):
                raise ProviderWebhookError("Shopify shop_domain must look like acme.myshopify.com.")
            if not token:
                raise ProviderWebhookError("Shopify credential requires access_token.")
            topic = str(config.get("topic") or "orders/create").strip()
            api_version = str(config.get("api_version") or "2024-10").strip()
            if not re.fullmatch(r"\d{4}-\d{2}", api_version):
                raise ProviderWebhookError("Shopify api_version must look like 2024-10.")
            if not signing_secret:
                raise ProviderWebhookError(
                    "Shopify registration requires the app client secret for HMAC verification."
                )
            response = await client.post(
                f"https://{domain}/admin/api/{api_version}/webhooks.json",
                headers={"X-Shopify-Access-Token": token},
                json={"webhook": {"topic": topic, "address": callback_url, "format": "json"}},
                timeout=30.0,
            )
            data = _json(response, "Shopify")
            raw_webhook = data.get("webhook")
            webhook = raw_webhook if isinstance(raw_webhook, dict) else {}
            if webhook.get("id") is None:
                raise ProviderWebhookError("Shopify did not return a webhook id.")
            return ProviderRegistrationResult(
                external_id=str(webhook["id"]),
                signing_secret=signing_secret,
                provider_config={"topic": topic, "api_version": api_version},
            )

        if provider == "typeform":
            token = str(credential.get("token") or "").strip()
            form_id = str(config.get("form_id") or "").strip()
            if not token:
                raise ProviderWebhookError("Typeform credential requires token.")
            if not TYPEFORM_FORM_RE.fullmatch(form_id):
                raise ProviderWebhookError(
                    "Typeform form_id must be 1-128 letters, numbers, underscores, or hyphens."
                )
            tag = str(config.get("tag") or "flowsmith").strip()
            if not TYPEFORM_TAG_RE.fullmatch(tag):
                raise ProviderWebhookError(
                    "Typeform webhook tag must be 1-64 letters, numbers, underscores, or hyphens."
                )
            secret = signing_secret
            if not secret:
                raise ProviderWebhookError("Typeform registration requires a webhook secret.")
            response = await client.put(
                f"https://api.typeform.com/forms/{quote(form_id, safe='')}/webhooks/{quote(tag, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
                json={"url": callback_url, "enabled": True, "secret": secret},
                timeout=30.0,
            )
            if getattr(response, "status_code", 0) >= 400:
                raise _response_error("Typeform", response)
            return ProviderRegistrationResult(
                external_id=tag,
                signing_secret=secret,
                provider_config={"form_id": form_id, "tag": tag},
            )

    raise ProviderWebhookError(f"Automatic webhook registration is not supported for {provider}.")


async def unregister_provider_webhook(
    *,
    provider: str,
    credential: dict[str, Any],
    external_id: str,
    config: dict[str, Any],
) -> None:
    from app.security.safe_http_client import get_safe_http_client

    if not external_id.strip():
        raise ProviderWebhookError("Provider webhook has no external id to remove.")
    async with get_safe_http_client() as client:
        if provider == "github":
            token = str(credential.get("access_token") or "").strip()
            repo = str(config.get("repository") or "").strip()
            response = await client.delete(
                f"https://api.github.com/repos/{repo}/hooks/{external_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        elif provider == "gitlab":
            token = str(credential.get("access_token") or "").strip()
            if not token:
                raise ProviderWebhookError("GitLab credential requires access_token.")
            project = _gitlab_project(config)
            base = str(credential.get("host") or "https://gitlab.com").strip().rstrip("/")
            if not base.startswith("https://"):
                raise ProviderWebhookError("GitLab credential host must use HTTPS.")
            response = await client.delete(
                f"{base}/api/v4/projects/{quote(project, safe='')}/hooks/{external_id}",
                headers={"PRIVATE-TOKEN": token},
                timeout=30.0,
            )
        elif provider == "stripe":
            key = str(credential.get("secret_key") or "").strip()
            response = await client.delete(
                f"https://api.stripe.com/v1/webhook_endpoints/{external_id}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=30.0,
            )
        elif provider == "shopify":
            domain = str(credential.get("shop_domain") or "").strip().lower()
            token = str(credential.get("access_token") or "").strip()
            api_version = str(config.get("api_version") or "2024-10").strip()
            response = await client.delete(
                f"https://{domain}/admin/api/{api_version}/webhooks/{external_id}.json",
                headers={"X-Shopify-Access-Token": token},
                timeout=30.0,
            )
        elif provider == "typeform":
            token = str(credential.get("token") or "").strip()
            form_id = str(config.get("form_id") or "").strip()
            tag = str(external_id or "").strip()
            if not TYPEFORM_FORM_RE.fullmatch(form_id):
                raise ProviderWebhookError(
                    "Typeform form_id must be 1-128 letters, numbers, underscores, or hyphens."
                )
            if not TYPEFORM_TAG_RE.fullmatch(tag):
                raise ProviderWebhookError(
                    "Typeform webhook tag must be 1-64 letters, numbers, underscores, or hyphens."
                )
            response = await client.delete(
                f"https://api.typeform.com/forms/{quote(form_id, safe='')}/webhooks/{quote(tag, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
        else:
            raise ProviderWebhookError(f"Automatic webhook removal is not supported for {provider}.")

        if getattr(response, "status_code", 0) >= 400 and getattr(response, "status_code", 0) != 404:
            raise _response_error(provider, response)
