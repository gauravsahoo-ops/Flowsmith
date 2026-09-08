# Phase 34 — Commercial/SaaS Foundation (billing, quotas, identity)

## Subscriptions & plans

- `subscriptions` table: one row per organization, **created lazily**
  (free default) so no migration/backfill for existing orgs. Tracks
  plan (`free|starter|pro|enterprise`), status
  (`active|trialing|past_due|canceled`) and Stripe identifiers.
- Plans and limits live in `app/billing/service.py`; enterprise is
  unlimited. Prices are inline Checkout `price_data` (no dashboard price
  setup needed): Starter $29/mo, Professional $99/mo.

## Stripe integration (`app/billing/__init__.py`, zero new deps)

- Raw REST via SafeHTTPClient with bearer auth.
- Subscription-mode Checkout Sessions with org/plan metadata.
- Webhook signature verification implementing Stripe's v1 HMAC-SHA256
  scheme with constant-time compare + 5-minute replay tolerance.
- Events handled: `checkout.session.completed` → activate;
  `customer.subscription.updated` → sync status/period;
  `customer.subscription.deleted` → downgrade to free/canceled.

**Self-host mode**: without `STRIPE_SECRET_KEY`, checkout returns 422 and
webhooks are rejected; plans/usage/check-limit keep working.

## Quota enforcement

- Resolution: workflow → workspace → organization → subscription.
- `POST /api/workflows/{id}/run` enforces the monthly execution budget
  (402 PAYMENT_REQUIRED with an upgrade hint when exhausted).
- `POST /api/workflows` (workspace-scoped) enforces the workflow-count
  cap — counted across all non-deleted workflows of the workspace.
- `BILLING_ENFORCEMENT=false` disables checks entirely (self-host).
- Existing endpoints stay compatible: check-limit still reports the
  display plan name (now plus a machine-readable `plan_key`).

New API: `GET /api/billing/subscription/{org}` ·
`POST /api/billing/checkout` · `POST /api/billing/stripe/webhook`
(public, signature-required).

## Product identity

Independent branding pass: **Flowsmith** (page title, login screen,
top bar). API paths, export envelope and storage keys are unchanged.

## Frontend

💳 Billing panel: organization selector, current plan/status card,
plan grid with Upgrade actions (redirects to Stripe Checkout), self-host
notice when checkout is disabled server-side.

## Tests (10 new; billing suite 17 green)

- Subscription lazy-default; checkout unconfigured 422 / invalid plan /
  session creation against scripted Stripe HTTP.
- Webhooks: activation, cancellation downgrade, tampered signature,
  expired timestamp, wrong secret (all rejected).
- Enforcement: run blocked at quota with 402, within-quota passes,
  workflow-create cap blocks at limit, enterprise unlimited passes,
  enforcement toggle honoured.

## Evidence

Backend **715 passed / 0 failed** · vitest 108/108 · Playwright E2E 6/6 ·
lint/build clean · pyright 0 errors on new modules.

## Known limitations / follow-ups

- Metered "API calls"/"storage" limits from the old stub were dropped in
  favour of the two quotas that map to real product surfaces today.
- No proration/seat handling; webhook endpoint is single-secret.
- Billing panel shows subscription state only (usage counters arrive
  with per-workspace dashboards).
