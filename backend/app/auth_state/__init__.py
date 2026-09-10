"""Workflow auth-state lifecycle (auth fetch/store nodes).

Token bundles live in `workflow_auth_state` (Fernet-encrypted), keyed by
(workflow_id, provider). Refresh reuses the existing OAuth2 engine
(`OAuthManager.refresh`); per-provider differences are DATA below, not
code branches. Static-token providers declare no refresh endpoint and
fail refresh fast with a clear reauth signal.
"""
