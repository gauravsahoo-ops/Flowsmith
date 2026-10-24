"""Provider-specific inbound webhook triggers.

These are not polling/official app trigger registrations. They are curated
webhook trigger presets that set the provider's signature header/encoding (or
plain token header for GitLab) and still use the existing public webhook
receiver.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.nodes.registry import register
from app.nodes.webhook import WebhookTriggerNode, WebhookTriggerParams


PROVIDER_SIGNATURE_DEFAULTS: dict[str, dict[str, object]] = {
    "github_trigger": {
        "signature_header": "x-hub-signature-256",
        "signature_prefix": "sha256=",
        "signature_algorithm": "sha256",
        "signature_encoding": "hex",
    },
    "stripe_trigger": {
        "signature_header": "stripe-signature",
        "signature_algorithm": "sha256",
    },
    "shopify_trigger": {
        "signature_header": "x-shopify-hmac-sha256",
        "signature_algorithm": "sha256",
        "signature_encoding": "base64",
    },
    "slack_trigger": {
        "signature_header": "x-slack-signature",
        "signature_prefix": "v0=",
        "signature_algorithm": "sha256",
        "timestamp_header": "x-slack-request-timestamp",
    },
    "typeform_trigger": {
        "signature_header": "typeform-signature",
        "signature_prefix": "sha256=",
        "signature_algorithm": "sha256",
        "signature_encoding": "base64",
    },
    "gitlab_trigger": {
        "token_header": "x-gitlab-token",
    },
}


def provider_signature_defaults(node_type: str) -> dict[str, object]:
    return dict(PROVIDER_SIGNATURE_DEFAULTS.get(node_type, {}))


class ProviderWebhookTriggerParams(WebhookTriggerParams):
    signature_header: str | None = Field(default=None, max_length=128)
    signature_algorithm: Literal["sha1", "sha256"] = "sha256"
    signature_encoding: Literal["hex", "base64"] = "hex"
    signature_prefix: str | None = Field(default=None, max_length=32)
    timestamp_header: str | None = Field(default=None, max_length=128)
    token_header: str | None = Field(default=None, max_length=128)


class GitHubTriggerParams(ProviderWebhookTriggerParams):
    signature_header: str | None = "x-hub-signature-256"
    signature_prefix: str | None = "sha256="


class StripeTriggerParams(ProviderWebhookTriggerParams):
    signature_header: str | None = "stripe-signature"


class ShopifyTriggerParams(ProviderWebhookTriggerParams):
    signature_header: str | None = "x-shopify-hmac-sha256"
    signature_encoding: Literal["hex", "base64"] = "base64"


class SlackTriggerParams(ProviderWebhookTriggerParams):
    signature_header: str | None = "x-slack-signature"
    signature_prefix: str | None = "v0="
    timestamp_header: str | None = "x-slack-request-timestamp"


class TypeformTriggerParams(ProviderWebhookTriggerParams):
    signature_header: str | None = "typeform-signature"
    signature_encoding: Literal["hex", "base64"] = "base64"
    signature_prefix: str | None = "sha256="


class GitLabTriggerParams(ProviderWebhookTriggerParams):
    token_header: str | None = "x-gitlab-token"


@register
class GitHubTriggerNode(WebhookTriggerNode):
    node_type = "github_trigger"
    display_name = "GitHub Trigger"
    description = "Receive signed GitHub webhook deliveries."
    parameters_schema = GitHubTriggerParams


@register
class StripeTriggerNode(WebhookTriggerNode):
    node_type = "stripe_trigger"
    display_name = "Stripe Trigger"
    description = "Receive Stripe events with timestamped signature verification."
    parameters_schema = StripeTriggerParams


@register
class ShopifyTriggerNode(WebhookTriggerNode):
    node_type = "shopify_trigger"
    display_name = "Shopify Trigger"
    description = "Receive Shopify webhooks with base64 HMAC verification."
    parameters_schema = ShopifyTriggerParams


@register
class SlackTriggerNode(WebhookTriggerNode):
    node_type = "slack_trigger"
    display_name = "Slack Trigger"
    description = "Receive Slack Events API requests with v0 signature verification."
    parameters_schema = SlackTriggerParams


@register
class TypeformTriggerNode(WebhookTriggerNode):
    node_type = "typeform_trigger"
    display_name = "Typeform Trigger"
    description = "Receive Typeform webhooks with base64 HMAC verification."
    parameters_schema = TypeformTriggerParams


@register
class GitLabTriggerNode(WebhookTriggerNode):
    node_type = "gitlab_trigger"
    display_name = "GitLab Trigger"
    description = "Receive GitLab webhooks authenticated with the X-Gitlab-Token header."
    parameters_schema = GitLabTriggerParams
