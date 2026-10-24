# Trigger Catalog

Flowsmith supports these trigger families:

| Trigger | Type | Notes |
|---|---|---|
| Manual | `manual_trigger` | Run from the editor/API. |
| Schedule | `schedule` | Cron/interval rules with timezone handling. |
| Webhook | `webhook` | Generic signed inbound HTTP receiver. |
| HTTP Polling | `http_poll_trigger` | Poll any JSON HTTP endpoint, extract items, deduplicate, and start the workflow. |
| GitHub | `github_trigger` | `X-Hub-Signature-256` hex HMAC preset. |
| GitLab | `gitlab_trigger` | Plain `X-Gitlab-Token` shared-token preset. |
| Stripe | `stripe_trigger` | `Stripe-Signature` timestamped HMAC preset. |
| Shopify | `shopify_trigger` | Base64 HMAC preset (`X-Shopify-Hmac-Sha256`). |
| Slack | `slack_trigger` | Slack `v0:` signature + timestamp replay guard. |
| Typeform | `typeform_trigger` | Base64 `sha256=` HMAC preset. |
| Salesforce | `salesforce_trigger` | Salesforce Outbound Message endpoint. |
| Form | `form_trigger` | Public form submissions. |
| Chat | `chat_trigger` | Public chat ingress. |
| SFTP | `sftp_trigger` | File arrival polling. |
| Error | `error_trigger` | Error workflow dispatch. |
| Sub-workflow | `execute_workflow_trigger` | Invoked by another workflow. |

## Provider-side registration

GitHub, GitLab, Stripe, Shopify, and Typeform can be registered directly through
Flowsmith after the workflow is active. Open the trigger editor and use
**Provider Webhook**:

- GitHub: repository (`owner/repo`) and events. Flowsmith creates a repository
  webhook with a generated secret and stores it encrypted.
- GitLab: project (`group/project`, nested groups supported) and events.
  Flowsmith creates a project hook using the credential's HTTPS host
  (`gitlab.com` by default) and a generated `X-Gitlab-Token`.
- Stripe: one or more enabled events. Stripe returns the endpoint signing secret,
  which Flowsmith stores encrypted and uses for inbound verification.
- Shopify: webhook topic plus the app client secret. The Admin API creates the
  webhook subscription.
- Typeform: form ID. Flowsmith creates/updates the `flowsmith` webhook tag with
  a generated secret.

Slack Events API registration is intentionally **not** automated: Slack apps
configure request URLs and event subscriptions in the Slack app dashboard.
`slack_trigger` remains a signed inbound receiver preset, not a provider
registration.

The API endpoints are:

- `POST /api/provider-webhooks/register`
- `GET /api/provider-webhooks?workflow_id=...`
- `DELETE /api/provider-webhooks/{id}` (optionally `?force=true` to queue a
  retry when the provider API is unavailable)

Registrations require an HTTPS `PUBLIC_URL` in production and a provider
credential of the matching type (`github`, `gitlab`, `stripe`, `shopify`, or `typeform`).
Trigger paths must be at least 24 characters, unique across active workflows,
and a single URL segment for provider callbacks. Provider paths are regenerated
on workflow import/duplicate. A forced unregister marks the registration
`orphaned` instead of deleting it, so the reaper can retry the provider-side
cleanup; the local record is removed only after the provider confirms deletion.
Cleanup is attempted every 60 seconds; failures are recorded in a sanitized
`last_error`, visible only to workflow editors/owners.

**Live verification note:** the automated tests cover registration, signing,
and removal against mocked provider APIs. This release has not been validated
against live GitHub, GitLab, Stripe, Shopify, or Typeform accounts in CI because
that requires real tenant credentials and public callback URLs.

**App-specific polling subscriptions** remain separate future work. Generic HTTP
polling is implemented and supports any JSON endpoint through the SSRF-safe
HTTP client.

## HTTP polling

`http_poll_trigger` polls `GET` or `POST` JSON endpoints on a 30–86,400 second
interval. `items_path` selects the array (for example `data.items`) and
`dedupe_field` selects the stable item identifier. New items are deduplicated
in the trigger row and started as one workflow execution. The daemon claims due
rows with `FOR UPDATE SKIP LOCKED`, so multiple API processes do not poll the
same trigger concurrently.

Polling URLs pass through the shared SSRF guard. Headers/body are part of the
workflow snapshot; use a dedicated least-privilege token and do not place
long-lived secrets in a polling trigger if your deployment does not treat
workflow snapshots as sensitive.

## Security

Provider presets merge signature defaults from the node type when the workflow
does not override them. The shared webhook verifier supports:

- hex and base64 HMAC digests;
- configurable signature headers and prefixes;
- Stripe timestamped signatures with a 300-second replay window;
- Slack `v0:timestamp:body` signatures with a 300-second replay window;
- provider delivery-ID deduplication (`X-GitHub-Delivery`,
  `X-Shopify-Webhook-Id`, `X-Gitlab-Event-UUID`, Typeform event IDs, and
  Stripe event IDs), with an exact signature/body fallback;
- constant-time signature comparison.

A configured `secret` is still required in production; unsigned webhooks are
open only in development. Provider-generated/returned secrets are stored
encrypted in `provider_webhook_registrations` and are never returned by the API.
