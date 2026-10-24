"""Application configuration from environment variables (spec 17: config.py).

Reads `.env` files too; all secrets must come from env, never defaults.

The application is PostgreSQL-only. Override the connection with the
``DATABASE_URL`` env var (or the default below, which matches the
compose Postgres). SQLite is used nowhere in the product.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            ".env",
            str(Path(__file__).resolve().parents[1] / ".env"),
            str(Path(__file__).resolve().parents[2] / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "database_url",
        "redis_url",
        "public_url",
        "jwt_secret",
        "credentials_encryption_key",
        "safe_http_allowed_hosts",
        "safe_http_allowed_ports",
        "app_env",
        "ldap_server_url",
        "ldap_bind_dn",
        "ldap_bind_password",
        "ldap_user_search_base",
        "ldap_user_search_filter",
        "ldap_user_email_attribute",
        "ldap_user_display_attribute",
        "ldap_group_search_base",
        "ldap_group_search_filter",
        "ldap_group_attribute",
        "ldap_group_role_map",
        "ldap_group_workspace_map",
        "ldap_group_org_map",
        "saml_group_attribute",
        "saml_group_role_map",
        "webauthn_rp_id",
        "webauthn_rp_name",
        "webauthn_origin",
        "webauthn_attestation",
        "webauthn_attestation_roots_file",
        "webauthn_allowed_aaguids",
        "webauthn_allowed_formats",
        mode="before",
    )
    @classmethod
    def _strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
        if v not in allowed:
            raise ValueError(f"Invalid JWT algorithm '{v}'. Must be one of: {', '.join(sorted(allowed))}")
        return v

    # Database (spec 17: make PostgreSQL authoritative). Default matches
    # docker-compose.yml (postgres service, user/db `automate`).
    database_url: str = "postgresql://automate:automate@localhost:5432/automate"
    # Connection pool sizing (per process: API + each worker scales these).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_s: int = 1800
    db_pool_pre_ping: bool = True

    # E2E: allow safe_http_client to bypass SSRF for the local stub server
    # (127.0.0.1:8181). read by app.security.safe_http_client as a fallback
    # when SAFE_HTTP_ALLOWED_HOSTS / SAFE_HTTP_ALLOWED_PORTS are not in the
    # process environment. Production deployments should leave these empty.
    safe_http_allowed_hosts: str = ""
    safe_http_allowed_ports: str = ""
    # Explicit opt-in for validate_production_settings: the allowlists above
    # disable the SSRF guard, so production refuses to boot with them set
    # unless ALLOW_SSRF_BYPASS is truthy. A Settings field (not os.getenv)
    # so .env-file values are honoured too.
    allow_ssrf_bypass: str = ""

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:5173"
    page_size_max: int = 100
    credentials_encryption_key: str = ""

    # Deployment mode (Phase 23 hardening): "development" (default) or
    # "production". Production startup refuses to run without the
    # mandatory secrets/backends (see validate_production_settings).
    app_env: str = "development"
    run_migrations_on_startup: bool = True

    # Self-service registration policy. The very first account is always
    # allowed (it bootstraps the installation and becomes the admin).
    # "open" = anyone; "invite" = requires REGISTRATION_INVITE_CODE;
    # "closed" = admins create accounts (no public self-service).
    registration_mode: str = "open"
    registration_invite_code: str = ""
    # Required in production. The first (admin) account must present this
    # out-of-band secret, so an attacker who reaches a fresh public instance
    # before the operator cannot win the admin role.
    registration_bootstrap_token: str = ""

    # Comma-separated proxy IPs/CIDRs whose X-Forwarded-For header may be
    # trusted. Localhost is safe by default; Docker/nginx deployments should
    # add their proxy network. Headers from any other peer are ignored, so a
    # direct internet client cannot spoof another client's IP.
    trusted_proxies: str = "127.0.0.1,::1"

    # Public deployment (M9): one port serves the built UI and the API.
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = ""
    serve_frontend: bool = True
    frontend_dist: str = str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    # File I/O node containment root (empty = <cwd>/data/files). Paths outside
    # this root (or the system temp dir) are refused with PATH_BLOCKED.
    file_io_root: str = ""
    # Phase 23/38: interactive API docs expose the whole route surface;
    # keep them for development, off in production unless explicitly on.
    api_docs_enabled: bool = False

    # Phase 33 (DR): transport for pg_dump/psql. "auto" prefers local
    # binaries and falls back to `docker exec` into pg_docker_container
    # (the server runs in Docker in dev/single-host deployments).
    pg_client_mode: str = "auto"  # auto | local | docker
    pg_docker_container: str = "mat-postgres"
    backup_retention_days: int = 14

    # Security & access (next phase): throttling, limits.
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    login_lockout_seconds: int = 300
    webhook_rate_limit: int = 60
    webhook_rate_period_s: int = 60

    # Password policy (spec 9: hardened authentication)
    password_min_length: int = 8
    password_require_uppercase: bool = True
    password_require_lowercase: bool = True
    password_require_number: bool = True
    password_require_symbol: bool = True
    password_max_attempts: int = 5
    password_expiry_days: int = 90

    # Per-user API rate limiting (middleware/rate_limit.py). The default
    # budget is UI-safe: the canvas polls execution status every 500ms and
    # autosaves, so a single active tab can legitimately issue a few
    # hundred requests per minute. Disable entirely in tests or when a
    # gateway (nginx/traefik) already enforces limits.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 300
    rate_limit_api_key_per_minute: int = 600

    # Data retention (M9 hardening): prune finished executions older
    # than this; the maintenance daemon runs on this interval.
    execution_retention_days: int = 30
    maintenance_prune_interval_hours: int = 24

    # Vector storage: PostgreSQL + pgvector is the production backend.
    # The `vector_store` key remains pluggable for tests/tools, but the
    # former embedded backends (sqlite_vec, chroma) have been retired;
    # their data was migratable via app.vectorstores.pgvector importer.
    vector_store: str = "pgvector"

    # Job queue & workers (Phase 15, spec 13/34/58): executions flow
    # through a job queue instead of running inline. `queue_backend` is
    # "db" (jobs table, zero infra, default) or "redis" (Redis lists,
    # requires `redis_url`). `queue_embedded_consumer` keeps a consumer
    # inside the API process (dev convenience); set it false to have the
    # API only enqueue, with external workers (`python -m app.queue.worker`)
    # doing the execution.
    queue_backend: str = "db"
    redis_url: str = ""
    redis_password: str = ""
    require_redis_auth: bool = False
    queue_embedded_consumer: bool = True
    worker_poll_interval_s: float = 0.5
    worker_heartbeat_s: float = 10.0
    worker_stale_seconds: float = 60.0
    worker_stale_sweep_s: float = 30.0
    queue_claim_timeout_s: float = 60.0  # job-level claim guard (spec 36)
    # Poison-job protection: stale-claim recovery stops re-queuing a job
    # once it has been claimed this many times and marks it FAILED instead.
    queue_max_attempts: int = 10
    # Exponential retry backoff for recovered jobs (claim N requeued with
    # delay base^(N-1), capped): avoids retry storms after incidents.
    queue_retry_backoff_base_s: float = 2.0
    queue_retry_backoff_max_s: float = 300.0
    # Redis-side retention of finished job bookkeeping (meta hashes). The
    # executions table stays authoritative; these keys are only debugging.
    redis_job_meta_ttl_s: int = 86400

    # Orphaned-execution reconciliation: an execution stuck in ``queued``
    # longer than this grace period is presumed lost by the queue backend
    # (e.g. Redis was flushed / its volume dropped) and is re-enqueued from
    # the authoritative execution row. The enqueue idempotency guard keeps
    # this safe when the job actually still exists in the store.
    execution_queued_grace_s: float = 300.0
    orphan_sweep_interval_s: float = 60.0

    # Salesforce "Connect Salesforce" OAuth (server-side Connected App):
    # end users authorize with THEIR Salesforce account; the app-level
    # client id/secret/redirect URI stay server-side and are never sent
    # to the frontend. SALESFORCE_REDIRECT_URI must EXACTLY match the
    # Callback URL registered in the Connected App.
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_redirect_uri: str = ""
    salesforce_login_url: str = "https://login.salesforce.com"
    salesforce_api_version: str = "v63.0"
    salesforce_scopes: str = "refresh_token full api"
    oauth_state_ttl_seconds: int = 600  # authorize-state validity window

    # HubSpot OAuth (Phase 33): the second first-party connector, built on
    # the same generic authorization-code flow as Salesforce. Server-side
    # app credentials, never exposed to the frontend. When
    # HUBSPOT_REDIRECT_URI is empty it derives from PUBLIC_URL
    # ({public_url}/api/auth/hubspot/callback).
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    hubspot_redirect_uri: str = ""
    hubspot_scopes: str = "oauth crm.objects.contacts.read crm.objects.contacts.write crm.objects.deals.read crm.objects.deals.write"

    # Google Calendar OAuth (Phase 37): third first-party connector.
    # access_type=offline + prompt=consent are forced so a refresh token
    # is always issued on (re-)connect.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    # Sheets / Gmail / Drive share the same Google OAuth app
    # (config_prefix=google), each with its own scope set + credential type.
    google_scopes: str = "openid email https://www.googleapis.com/auth/calendar.events"
    google_sheets_scopes: str = (
        "openid email https://www.googleapis.com/auth/spreadsheets"
    )
    gmail_scopes: str = (
        "openid email https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/gmail.readonly"
    )
    # Google Drive connector (Phase 11): same shared Google app, Drive scope.
    google_drive_scopes: str = (
        "openid email https://www.googleapis.com/auth/drive"
    )
    # Google Docs connector: same shared Google app, documents scope.
    google_docs_scopes: str = (
        "openid email https://www.googleapis.com/auth/documents"
    )

    # Microsoft Dynamics 365 CRM (Dataverse)
    dynamics_crm_client_id: str = ""
    dynamics_crm_client_secret: str = ""
    dynamics_crm_redirect_uri: str = ""
    dynamics_crm_tenant_id: str = "common"
    dynamics_crm_instance_url: str = ""
    dynamics_crm_scopes: str = "offline_access https://admin.services.crm.dynamics.com/user_impersonation"

    # Password self-service reset (Phase 42). SMTP is optional: when
    # unset (or APP_ENV != production) the reset link is surfaced in the
    # API response / server log so local users can complete the flow.
    password_reset_ttl_seconds: int = 1800  # 30 min
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    smtp_use_tls: bool = False
    smtp_starttls: bool = True

    # Error Monitoring & Alert System
    error_monitoring_enabled: bool = True
    error_notification_cooldown_minutes: int = 15
    error_notification_max_retries: int = 3
    error_notification_admin_email: str = ""
    app_base_url: str = "http://localhost:5173"  # Frontend URL for actionable email links

    # Billing / SaaS (Phase 34). With STRIPE_SECRET_KEY unset the app runs
    # in self-host mode: plan data exists, checkout/webhooks are disabled.
    # BILLING_ENFORCEMENT=false disables quota checks entirely (self-host).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    billing_enforcement: bool = False

    # Object storage (Phase 19): S3-compatible abstraction for files and
    # large artifacts. `local` (filesystem) is the default for development
    # and keeps the Docker image dependency-free; `s3` uses any S3-
    # compatible provider (AWS, MinIO, R2...). See app/objectstore/.
    object_store_backend: str = "local"  # local | s3
    object_store_local_path: str = "./data/objects"
    object_store_bucket: str = ""
    object_store_endpoint: str = ""  # e.g. http://minio:9000 for MinIO
    object_store_region: str = "us-east-1"
    object_store_access_key: str = ""
    object_store_secret_key: str = ""
    object_store_force_path_style: bool = True

    # Single Sign-On (SSO): Google, GitHub, and generic OIDC (Okta, Keycloak, Auth0, Azure AD)
    sso_google_client_id: str = ""
    sso_google_client_secret: str = ""
    sso_github_client_id: str = ""
    sso_github_client_secret: str = ""
    sso_oidc_issuer: str = ""
    sso_oidc_client_id: str = ""
    sso_oidc_client_secret: str = ""
    sso_oidc_display_name: str = "Enterprise SSO"

    # SCIM 2.0 user provisioning. Disabled by default; enable with a
    # dedicated bearer token and an optional default organization/workspace
    # for newly provisioned users.
    scim_enabled: bool = False
    scim_bearer_token: str = ""
    scim_default_organization_id: str = ""
    scim_default_workspace_id: str = ""
    # SCIM groups are materialized as private workspaces. A group owner is
    # selected by email, or the first active administrator when omitted.
    scim_group_organization_id: str = ""
    scim_group_owner_email: str = ""

    # LDAP authentication (local password login falls back to LDAP when the
    # local password does not match). LDAPS or StartTLS is required in
    # production; group names can be mapped to Flowsmith roles with a JSON
    # object such as {"workflow-admins": "admin"}.
    ldap_enabled: bool = False
    ldap_server_url: str = ""
    ldap_start_tls: bool = False
    ldap_tls_verify: bool = True
    ldap_ca_cert_file: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_search_base: str = ""
    ldap_user_search_filter: str = "(uid={username})"
    ldap_user_email_attribute: str = "mail"
    ldap_user_display_attribute: str = "displayName"
    ldap_group_search_base: str = ""
    ldap_group_search_filter: str = "(member={user_dn})"
    ldap_group_attribute: str = "cn"
    ldap_group_role_map: str = ""
    # Optional group -> workspace memberships. JSON object values may be a
    # workspace ID string or an object {"workspace_id","role","permission"}.
    ldap_group_workspace_map: str = ""
    # Optional group -> organization memberships. Values may be an
    # organization ID string or {"organization_id","role","permission"}.
    ldap_group_org_map: str = ""
    ldap_default_role: str = "member"
    ldap_jit_provisioning: bool = True
    ldap_default_organization_id: str = ""
    ldap_default_workspace_id: str = ""
    ldap_connect_timeout_seconds: int = 5
    ldap_receive_timeout_seconds: int = 10
    # Background group/profile refresh. Disabled by default; enable it only
    # after the login path and service account have been validated.
    ldap_sync_enabled: bool = False
    ldap_sync_interval_seconds: int = 900

    # WebAuthn/passkeys. Disabled by default because a correct RP ID and
    # origin are deployment-specific; enable after setting both explicitly.
    webauthn_enabled: bool = False
    webauthn_rp_id: str = ""
    webauthn_rp_name: str = "Flowsmith"
    webauthn_origin: str = ""
    webauthn_require_uv: bool = True
    webauthn_timeout_ms: int = 60000
    # "none" accepts any authenticator; "direct"/"enterprise" request
    # attestation and require a trusted attestation root + policy match.
    webauthn_attestation: str = "none"
    webauthn_attestation_roots_file: str = ""
    webauthn_allowed_aaguids: str = ""
    webauthn_allowed_formats: str = ""

    # Native SAML 2.0 Web SSO. IdP metadata can be loaded from a URL or
    # supplied inline for air-gapped installations. SP request signing is
    # optional; assertion/response signatures are always required.
    saml_enabled: bool = False
    saml_display_name: str = "SAML 2.0"
    saml_idp_metadata_url: str = ""
    saml_idp_metadata_xml: str = ""
    saml_idp_entity_id: str = ""
    saml_idp_x509_cert: str = ""
    saml_sp_entity_id: str = ""
    saml_sp_acs_url: str = ""
    saml_sp_x509_cert: str = ""
    saml_sp_private_key: str = ""
    saml_jit_provisioning: bool = True
    saml_default_role: str = "member"
    saml_role_attribute: str = "role"
    # Optional IdP group claim: JSON map such as {"platform-admins":"admin"}.
    saml_group_attribute: str = "groups"
    saml_group_role_map: str = ""
    saml_default_organization_id: str = ""
    saml_default_workspace_id: str = ""
    saml_allow_idp_initiated: bool = False
    saml_clock_skew_seconds: int = 120
    saml_metadata_cache_seconds: int = 300

    # Connector packs. Remote manifest URLs always require a valid Ed25519
    # signature. Set CONNECTOR_PACK_REQUIRE_SIGNATURE=true to require signatures
    # for inline manifests too. Trusted keys are a JSON map:
    # {"release-2026": "<PEM or base64 raw Ed25519 public key>"}.
    connector_pack_require_signature: bool = False
    connector_pack_trusted_keys: str = ""
    # Comma-separated signing key IDs that must no longer be accepted.
    connector_pack_revoked_keys: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ConfigError(RuntimeError):
    """Raised when the application refuses to start with invalid config."""


def validate_production_settings(settings: Settings | None = None) -> None:
    """Fail fast on production config that would be unsafe.

    Call once at startup. Development defaults never satisfy these
    checks, so production must be explicit (APP_ENV=production).
    """
    settings = settings or get_settings()
    if settings.app_env != "production":
        return
    missing: list[str] = []
    if not settings.credentials_encryption_key:
        missing.append("CREDENTIALS_ENCRYPTION_KEY")
    elif len(settings.credentials_encryption_key) < 16:
        missing.append("CREDENTIALS_ENCRYPTION_KEY (key too short)")
    if not settings.jwt_secret or settings.jwt_secret in ("dev-only-secret-change-me", "changeme", "secret", "password"):
        missing.append("JWT_SECRET (must be set to a secure random value)")
    elif len(settings.jwt_secret) < 32:
        missing.append("JWT_SECRET (must be at least 32 characters in production)")
    db_url = (settings.database_url or "").lower()
    if "sqlite" in db_url:
        missing.append("DATABASE_URL (must be PostgreSQL in production)")
    elif ":automate@" in db_url:
        missing.append("DATABASE_URL (default development password detected in production)")
    origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
    if not origins:
        missing.append("CORS_ORIGINS (explicit allowed origins must be configured in production)")
    elif "*" in origins:
        # CORS allow_origins="*" combined with allow_credentials=True is an
        # unsafe combination for a deployed API surface (main.py sets
        # credentials=True unconditionally).
        missing.append("CORS_ORIGINS (wildcard '*' is not allowed in production)")
    reg_mode = (settings.registration_mode or "open").strip().lower()
    if reg_mode not in ("open", "invite", "closed"):
        missing.append("REGISTRATION_MODE (must be open, invite, or closed)")
    elif reg_mode == "invite" and len(settings.registration_invite_code or "") < 16:
        missing.append("REGISTRATION_INVITE_CODE (at least 16 characters when REGISTRATION_MODE=invite)")
    if settings.connector_pack_require_signature and not (settings.connector_pack_trusted_keys or "").strip():
        missing.append("CONNECTOR_PACK_TRUSTED_KEYS (required when CONNECTOR_PACK_REQUIRE_SIGNATURE=true)")

    # Redis authentication & queue integrity
    redis_url = settings.redis_url or ""
    url_pw = ""
    if "@" in redis_url:
        auth_part = redis_url.split("@")[0].split("//")[-1]
        if ":" in auth_part:
            url_pw = auth_part.split(":", 1)[1]
    effective_redis_pw = settings.redis_password or url_pw
    insecure_redis_passwords = {"changeme", "password", "redis", "default", "admin", "123456", "root"}

    if effective_redis_pw and effective_redis_pw.lower() in insecure_redis_passwords:
        missing.append("REDIS_PASSWORD (insecure default password detected)")

    if settings.queue_backend == "redis":
        if not settings.redis_url:
            missing.append("REDIS_URL (required when QUEUE_BACKEND=redis)")
        elif settings.require_redis_auth and not effective_redis_pw:
            missing.append("REDIS_PASSWORD (Redis authentication required when REQUIRE_REDIS_AUTH=true)")

    if settings.require_redis_auth and not effective_redis_pw:
        msg = "REDIS_PASSWORD (Redis authentication required when REQUIRE_REDIS_AUTH=true)"
        if msg not in missing:
            missing.append(msg)

    if settings.scim_enabled and len(settings.scim_bearer_token or "") < 32:
        missing.append("SCIM_BEARER_TOKEN (at least 32 characters when SCIM_ENABLED=true)")
    if settings.saml_enabled:
        if not (settings.public_url or "").strip():
            missing.append("PUBLIC_URL (required when SAML_ENABLED=true)")
        elif not settings.public_url.lower().startswith("https://"):
            missing.append("PUBLIC_URL (must use HTTPS when SAML_ENABLED=true)")
        if not (settings.saml_idp_metadata_url or settings.saml_idp_metadata_xml):
            missing.append("SAML_IDP_METADATA_URL or SAML_IDP_METADATA_XML (required when SAML_ENABLED=true)")
        if (
            settings.saml_idp_metadata_url
            and not settings.saml_idp_metadata_url.lower().startswith("https://")
        ):
            missing.append("SAML_IDP_METADATA_URL (must use HTTPS in production)")
        if settings.saml_sp_x509_cert and not settings.saml_sp_private_key:
            missing.append("SAML_SP_PRIVATE_KEY (required when SAML_SP_X509_CERT is set)")
        if (settings.saml_default_role or "").strip().lower() not in ("admin", "member"):
            missing.append("SAML_DEFAULT_ROLE (must be admin or member)")
        if settings.saml_group_role_map.strip():
            import json

            try:
                group_roles = json.loads(settings.saml_group_role_map)
            except ValueError:
                group_roles = None
            if not isinstance(group_roles, dict) or any(
                str(role).strip().lower() not in ("admin", "member")
                for role in (group_roles or {}).values()
            ):
                missing.append("SAML_GROUP_ROLE_MAP (must be a JSON object with admin/member values)")
    if settings.webauthn_enabled:
        if not settings.webauthn_rp_id:
            missing.append("WEBAUTHN_RP_ID (required when WEBAUTHN_ENABLED=true)")
        if not settings.webauthn_origin:
            missing.append("WEBAUTHN_ORIGIN (required when WEBAUTHN_ENABLED=true)")
        elif not settings.webauthn_origin.lower().startswith("https://"):
            missing.append("WEBAUTHN_ORIGIN (must use HTTPS in production)")
        elif settings.webauthn_rp_id:
            from urllib.parse import urlparse

            origin_host = (urlparse(settings.webauthn_origin).hostname or "").lower()
            rp_id = settings.webauthn_rp_id.lower()
            if origin_host != rp_id and not origin_host.endswith("." + rp_id):
                missing.append("WEBAUTHN_RP_ID (must match WEBAUTHN_ORIGIN host)")
        attestation = (settings.webauthn_attestation or "none").strip().lower()
        if attestation not in ("none", "direct", "enterprise"):
            missing.append("WEBAUTHN_ATTESTATION (must be none, direct, or enterprise)")
        elif attestation != "none":
            if not settings.webauthn_attestation_roots_file:
                missing.append("WEBAUTHN_ATTESTATION_ROOTS_FILE (required for attestation)")
            else:
                from pathlib import Path

                if not Path(settings.webauthn_attestation_roots_file).is_file():
                    missing.append("WEBAUTHN_ATTESTATION_ROOTS_FILE (file does not exist)")
    if settings.ldap_enabled:
        if not settings.ldap_server_url:
            missing.append("LDAP_SERVER_URL (required when LDAP_ENABLED=true)")
        elif not settings.ldap_server_url.lower().startswith(("ldaps://", "ldap://")):
            missing.append("LDAP_SERVER_URL (must be ldap:// or ldaps://)")
        elif (
            not settings.ldap_server_url.lower().startswith("ldaps://")
            and not settings.ldap_start_tls
        ):
            missing.append("LDAP_SERVER_URL (use ldaps:// or LDAP_START_TLS=true in production)")
        if not settings.ldap_tls_verify:
            missing.append("LDAP_TLS_VERIFY (must be true in production)")
        if not settings.ldap_user_search_base:
            missing.append("LDAP_USER_SEARCH_BASE (required when LDAP_ENABLED=true)")
        if settings.ldap_user_search_filter.count("{username}") != 1:
            missing.append("LDAP_USER_SEARCH_FILTER (must contain {username} exactly once)")
        if settings.ldap_group_search_base and settings.ldap_group_search_filter.count("{user_dn}") != 1:
            missing.append("LDAP_GROUP_SEARCH_FILTER (must contain {user_dn} exactly once)")
        if (settings.ldap_default_role or "").strip().lower() not in ("admin", "member"):
            missing.append("LDAP_DEFAULT_ROLE (must be admin or member)")
        if settings.ldap_group_role_map.strip():
            import json

            try:
                role_map = json.loads(settings.ldap_group_role_map)
            except ValueError:
                role_map = None
            if not isinstance(role_map, dict) or any(
                str(role).strip().lower() not in ("admin", "member")
                for role in (role_map or {}).values()
            ):
                missing.append("LDAP_GROUP_ROLE_MAP (must be a JSON object with admin/member values)")
        if settings.ldap_group_workspace_map.strip():
            import json

            try:
                workspace_map = json.loads(settings.ldap_group_workspace_map)
            except ValueError:
                workspace_map = None
            if not isinstance(workspace_map, dict):
                missing.append("LDAP_GROUP_WORKSPACE_MAP (must be a JSON object)")
            else:
                for grants in workspace_map.values():
                    entries = grants if isinstance(grants, list) else [grants]
                    for entry in entries:
                        if isinstance(entry, str):
                            continue
                        if not isinstance(entry, dict) or not str(
                            entry.get("workspace_id") or ""
                        ).strip():
                            missing.append(
                                "LDAP_GROUP_WORKSPACE_MAP (entries need workspace_id)"
                            )
                            break
                        if str(entry.get("role") or "member").strip().lower() not in (
                            "admin", "member"
                        ):
                            missing.append(
                                "LDAP_GROUP_WORKSPACE_MAP (role must be admin or member)"
                            )
                        if str(entry.get("permission") or "edit").strip().lower() not in (
                            "view", "edit", "admin"
                        ):
                            missing.append(
                                "LDAP_GROUP_WORKSPACE_MAP (permission must be view/edit/admin)"
                            )
        if settings.ldap_group_org_map.strip():
            import json

            try:
                org_map = json.loads(settings.ldap_group_org_map)
            except ValueError:
                org_map = None
            if not isinstance(org_map, dict):
                missing.append("LDAP_GROUP_ORG_MAP (must be a JSON object)")
            else:
                for grants in org_map.values():
                    entries = grants if isinstance(grants, list) else [grants]
                    for entry in entries:
                        if isinstance(entry, str):
                            continue
                        if not isinstance(entry, dict) or not str(
                            entry.get("organization_id") or ""
                        ).strip():
                            missing.append(
                                "LDAP_GROUP_ORG_MAP (entries need organization_id)"
                            )
                            break
                        if str(entry.get("role") or "member").strip().lower() not in (
                            "admin", "member"
                        ):
                            missing.append(
                                "LDAP_GROUP_ORG_MAP (role must be admin or member)"
                            )
                        if str(entry.get("permission") or "view").strip().lower() not in (
                            "view", "edit", "admin"
                        ):
                            missing.append(
                                "LDAP_GROUP_ORG_MAP (permission must be view/edit/admin)"
                            )
        if settings.ldap_sync_interval_seconds < 60:
            missing.append("LDAP_SYNC_INTERVAL_SECONDS (must be at least 60)")
    if settings.billing_enforcement:
        if not settings.stripe_secret_key:
            missing.append("STRIPE_SECRET_KEY (required when BILLING_ENFORCEMENT=true)")
        if not settings.stripe_webhook_secret:
            missing.append("STRIPE_WEBHOOK_SECRET (required when BILLING_ENFORCEMENT=true)")
    if missing:
        raise ConfigError(
            "Refusing to start in production mode: missing "
            + ", ".join(missing)
            + "."
        )
    # SSRF escape hatches must be a conscious, separate opt-in: the exact-
    # host/port allowlists silently disable the guard for every request, so
    # production refuses to boot with them set unless explicitly overridden.
    # (Read from Settings — a plain os.getenv would miss .env-file values.)
    if (settings.safe_http_allowed_hosts.strip() or settings.safe_http_allowed_ports.strip()) and (
        settings.allow_ssrf_bypass.strip().lower() not in ("1", "true", "yes")
    ):
        raise ConfigError(
            "Refusing to start in production mode: SAFE_HTTP_ALLOWED_HOSTS / "
            "SAFE_HTTP_ALLOWED_PORTS enable an SSRF bypass. Unset them, or set "
            "ALLOW_SSRF_BYPASS=true explicitly if this deployment intends it."
        )
