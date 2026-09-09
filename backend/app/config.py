"""Application configuration from environment variables (spec 17: config.py).

Reads `.env` files too; all secrets must come from env, never defaults.

The application is PostgreSQL-only. Override the connection with the
``DATABASE_URL`` env var (or the default below, which matches the
compose Postgres). SQLite is used nowhere in the product.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    cors_origins: str = "*"
    page_size_max: int = 100
    credentials_encryption_key: str = ""

    # Deployment mode (Phase 23 hardening): "development" (default) or
    # "production". Production startup refuses to run without the
    # mandatory secrets/backends (see validate_production_settings).
    app_env: str = "development"

    # Public deployment (M9): one port serves the built UI and the API.
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = ""
    serve_frontend: bool = True
    frontend_dist: str = str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
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
    gmail_scopes: str = "openid email https://www.googleapis.com/auth/gmail.send"
    # Google Drive connector (Phase 11): same shared Google app, Drive scope.
    google_drive_scopes: str = (
        "openid email https://www.googleapis.com/auth/drive"
    )

    # Password self-service reset (Phase 42). SMTP is optional: when
    # unset (or APP_ENV != production) the reset link is surfaced in the
    # API response / server log so local users can complete the flow.
    password_reset_ttl_seconds: int = 1800  # 30 min
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""

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
    if not settings.jwt_secret or settings.jwt_secret == "dev-only-secret-change-me":
        missing.append("JWT_SECRET (dev default)")
    if "sqlite" in (settings.database_url or "").lower():
        missing.append("DATABASE_URL (must be PostgreSQL in production)")
    origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
    if "*" in origins:
        # CORS allow_origins="*" combined with allow_credentials=True is an
        # unsafe combination for a deployed API surface (main.py sets
        # credentials=True unconditionally).
        missing.append("CORS_ORIGINS (wildcard '*' is not allowed in production)")
    if missing:
        raise ConfigError(
            "Refusing to start in production mode: missing "
            + ", ".join(missing)
            + "."
        )