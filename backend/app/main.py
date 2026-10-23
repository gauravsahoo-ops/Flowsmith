"""FastAPI application entry point (spec 17: main.py).

M9: when `serve_frontend` is enabled and the built frontend exists, the
app also serves the UI (SPA fallback to index.html) so one port runs the
whole product: UI, API, webhooks and the live WebSocket stream.
Phase 7: structured request logging + Prometheus-style metrics at
GET /api/metrics.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message

from app.api import admin, ai, audit, auth, billing, branding, code, connectors, credentials, data_tables, environments, executions, files, integrations, llm, mcp, monitoring, nodes, notifications, oauth, organizations, rag, salesforce_events, sso, users, webhooks, workflow_api, workflow_tests, workflows, workspaces, ws
from app.api.auth import get_metrics_user
from app.api.common import ok
from app.config import get_settings
from app.metrics import http_duration, http_requests
from app.telemetry.middleware import OpenTelemetryMiddleware

logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.config import validate_production_settings
    from app.db import get_engine, get_session, init_db, verify_schema_state
    from app.lifecycle import StartupStage, get_lifecycle
    from app.maintenance import maintenance
    from app.queue.worker import ensure_embedded_consumer, stop_embedded_consumer
    from app.runner import runner
    from app.scheduler import scheduler
    from app.services.connection_health_monitor import connection_health_monitor
    from app.triggers.registry import sync_webhooks

    lifecycle = get_lifecycle()

    try:
        # Stage 1: CONFIG_VALIDATION
        lifecycle.transition_to(StartupStage.CONFIG_VALIDATION, "Validating production settings")
        validate_production_settings()

        # Stage 2: DATABASE_CONNECTIVITY
        lifecycle.transition_to(StartupStage.DATABASE_CONNECTIVITY, "Establishing database engine connectivity")
        eng = get_engine()
        db_connected = False
        last_conn_err = None
        for attempt in range(1, 16):
            try:
                with eng.connect() as conn:
                    conn.execute(select(1))
                db_connected = True
                break
            except Exception as exc:
                last_conn_err = exc
                logger.warning("Database connectivity attempt %d/15 failed (%s). Retrying in 2s...", attempt, exc)
                time.sleep(2.0)
        if not db_connected and last_conn_err:
            raise last_conn_err

        # Stage 3: SCHEMA_REVISION_VERIFICATION
        lifecycle.transition_to(StartupStage.SCHEMA_REVISION_VERIFICATION, "Verifying and synchronizing schema revisions")
        init_db()
        schema_info = verify_schema_state(eng)
        lifecycle.set_metadata("schema_revision", schema_info.get("current_revision"))
        lifecycle.set_metadata("expected_revision", schema_info.get("expected_revision"))
        lifecycle.set_metadata("schema_drift_ok", schema_info.get("ok"))
        if not schema_info.get("ok"):
            logger.warning(
                "Schema drift detected: current=%s expected=%s status=%s",
                schema_info.get("current_revision"),
                schema_info.get("expected_revision"),
                schema_info.get("status"),
            )

        # Stage 4: CONNECTOR_REGISTRY_INIT
        lifecycle.transition_to(StartupStage.CONNECTOR_REGISTRY_INIT, "Registering built-in and parity connectors")
        from app.connectors import get_registry, register_builtin_connectors

        register_builtin_connectors()
        registry = get_registry()
        lifecycle.set_metadata("connectors_count", len(registry.list_definitions()))
        lifecycle.set_metadata("connector_diagnostics", registry.get_diagnostics())

        # Stage 5: REDIS_CONNECTIVITY
        lifecycle.transition_to(StartupStage.REDIS_CONNECTIVITY, "Verifying Redis client connection if configured")
        needs_redis = bool(get_settings().redis_url) or get_settings().queue_backend == "redis"
        if needs_redis:
            from app.security.redis_client import get_shared_redis

            r_client = get_shared_redis()
            if r_client is not None:
                r_client.ping()
                lifecycle.set_metadata("redis", "connected")
            else:
                lifecycle.set_metadata("redis", "unavailable")
        else:
            lifecycle.set_metadata("redis", "not_configured")

        # Stage 6: SERVICE_INITIALIZATION
        lifecycle.transition_to(StartupStage.SERVICE_INITIALIZATION, "Initializing runner, scheduler, and workers")
        db = get_session()
        try:
            sync_webhooks(db)
        finally:
            db.close()
        runner.submit(scheduler.ensure_started)
        runner.submit(connection_health_monitor.ensure_started)
        ensure_embedded_consumer()

        # Stage 7: STARTUP_COMPLETE
        lifecycle.transition_to(StartupStage.STARTUP_COMPLETE, "Application startup complete.")
        logger.info("Application startup complete.")

        # Stage 8: READINESS_ENABLED
        lifecycle.transition_to(StartupStage.READINESS_ENABLED, "Readiness probes active.")

    except Exception as exc:
        lifecycle.mark_failed(exc, lifecycle.current_stage)
        logger.exception("Application startup failed at stage %s: %s", lifecycle.current_stage.value, exc)
        raise

    yield

    lifecycle.transition_to(StartupStage.SHUTTING_DOWN, "Graceful application shutdown initiated")
    stop_embedded_consumer()
    try:
        await connection_health_monitor.stop()
    except Exception:
        logger.exception("connection_health_monitor stop failed")
    try:
        await maintenance.stop()
    except Exception:
        logger.exception("maintenance stop failed")
    runner.shutdown()
    # Close the shared HTTP client pool (P1: connection pool fix)
    from app.security.safe_http_client import get_safe_http_client as _get_http
    await _get_http().close()


settings = get_settings()
# Phase 23/38: interactive docs are a development convenience and leak
# the full route surface; disabled unless explicitly enabled.
_docs = "/docs" if get_settings().api_docs_enabled else None
_redoc = "/redoc" if get_settings().api_docs_enabled else None
_openapi = "/openapi.json" if get_settings().api_docs_enabled else None
app = FastAPI(title="Flowsmith API", version="1.6.0", lifespan=lifespan,
              docs_url=_docs, redoc_url=_redoc, openapi_url=_openapi)

FRONTEND_DIST: Path | None = Path(settings.frontend_dist) if settings.serve_frontend else None


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """M9: serve the built UI from the same port.

    Real files are served as-is; anything else the app 404s on falls
    back to index.html (client-side routing). /api and /ws paths are
    never touched, so router semantics (404/405/…) are preserved.
    """

    @staticmethod
    def _index_response(request: Request) -> HTMLResponse:
        """Serve index.html with a per-response CSP nonce for style injection.

        Monaco (and some UI libraries) create <style> elements at runtime.
        A nonce lets the built UI run without `style-src 'unsafe-inline'`
        while static React style attributes remain covered by style-src-attr.
        """
        assert FRONTEND_DIST is not None
        from html import escape

        nonce = secrets.token_urlsafe(18)
        request.state.csp_nonce = nonce
        html = (FRONTEND_DIST / "index.html").read_text(encoding="utf-8")
        meta = f'<meta name="csp-nonce" content="{escape(nonce)}" />'
        if "</head>" in html:
            html = html.replace("</head>", meta + "</head>", 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in ("GET", "HEAD"):
            return await call_next(request)
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/ws/") or path in ("/readyz", "/api/readyz", "/health"):
            return await call_next(request)
        if FRONTEND_DIST is not None:
            root = FRONTEND_DIST.resolve()
            candidate = (root / path.lstrip("/")).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                if candidate.name == "index.html":
                    return self._index_response(request)
                headers: dict[str, str] = {}
                if "/assets/" in path or path.startswith("assets/"):
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return FileResponse(candidate, headers=headers)
        response = await call_next(request)
        if (
            response.status_code == 404
            and ".." not in path
            and FRONTEND_DIST is not None
            and (FRONTEND_DIST / "index.html").is_file()
        ):
            return self._index_response(request)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Production security headers on every response.

    Adds standard hardening headers: clickjacking, MIME sniffing,
    referrer policy, and (when not localhost) HSTS.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # blob: is required for same-origin object-URL previews (images,
        # sandboxed PDF iframes, and fetch() of fetched file blobs);
        # fonts.* origins back the Google Fonts <link> in index.html.
        # Served UI responses carry a per-response nonce for dynamic <style>
        # elements (Monaco); API responses have no nonce and keep the
        # attribute-only allowance.
        nonce = getattr(request.state, "csp_nonce", None)
        if nonce:
            style_src = f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; style-src-attr 'unsafe-inline'; "
        else:
            style_src = "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            + style_src
            + "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; media-src 'self' data: blob:; "
            "connect-src 'self' blob:; worker-src 'self' blob:; "
            "frame-src 'self' blob: data:; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        # HSTS is a deployment property, not a request property: deciding it
        # from the Host header lets a forged/plain-HTTP request suppress it.
        settings = get_settings()
        if settings.app_env == "production" or (settings.public_url or "").lower().startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Origin/Referer validation on state-changing requests (defense-in-depth).

    Even though the API uses JWT Bearer tokens (not cookies), CSRF
    protection is applied as a layered defense.  On POST/PUT/PATCH/DELETE
    the middleware checks the Origin or Referer header against the
    configured allowed origins (CORS_ORIGINS + PUBLIC_URL).  Requests
    missing both headers (e.g. curl, server-to-server) are allowed
    through — only cross-origin browser requests are blocked.

    Skipped in development when CORS_ORIGINS is wildcard and no
    PUBLIC_URL is set (local dev has no origin to validate against).
    """

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _SAFE_PREFIXES = ("/api/health", "/readyz", "/api/readyz", "/docs", "/redoc", "/openapi.json", "/api/auth", "/api/webhooks")

    def __init__(self, app: Any, allowed_origins: list[str]) -> None:
        super().__init__(app)
        # Build a set of allowed hostname:port pairs from configured origins
        self._allowed: set[str] = set()
        for origin in allowed_origins:
            origin = origin.strip().rstrip("/")
            if origin == "*":
                continue
            # Extract host from full origin (https://example.com -> example.com)
            if "://" in origin:
                from urllib.parse import urlparse
                parsed = urlparse(origin)
                if parsed.hostname:
                    self._allowed.add(parsed.hostname.lower())
            else:
                # Bare hostname or hostname:port
                host = origin.split(":")[0].lower()
                self._allowed.add(host)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip safe methods and public endpoints
        if request.method in self._SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in self._SAFE_PREFIXES):
            return await call_next(request)
        # No allowed origins configured — can't validate (dev mode)
        if not self._allowed:
            return await call_next(request)

        # Extract origin from Origin header, fall back to Referer
        origin_header = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        check_value = origin_header or referer

        # No Origin/Referer — server-to-server or curl, allow through
        if not check_value:
            return await call_next(request)

        # Extract hostname from the check value
        if "://" in check_value:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(check_value)
                req_host = (parsed.hostname or "").lower()
            except Exception:
                return Response(status_code=403, content="CSRF validation failed: malformed origin")
        else:
            req_host = check_value.split(":")[0].lower()

        # Allow same-origin requests (host matches any configured origin)
        if req_host in self._allowed or req_host in ("127.0.0.1", "localhost", "::1"):
            return await call_next(request)

        # Allow same-origin requests matching the request's own Host or X-Forwarded-Host
        host_header = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        current_host = host_header.split(":")[0].lower() if host_header else (request.url.hostname or "").lower()
        if req_host and current_host and (req_host == current_host or req_host == (request.url.hostname or "").lower()):
            return await call_next(request)

        return Response(status_code=403, content="CSRF validation failed: cross-origin request rejected")


class MetricsMiddleware(BaseHTTPMiddleware):
    """Phase 7: per-request metrics + one structured log line.

    Logs method/path/status/duration only — never headers or bodies.
    Paths use the route template when available (bounded cardinality);
    unmatched paths are truncated to 80 chars.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", None) if route is not None else None
        if path is None:
            path = request.url.path[:80]
        method = request.method
        status = response.status_code
        http_requests.inc((method, path, str(status)))
        http_duration.observe(duration, (method, path))
        logger.info(
            "request %s %s -> %s",
            method,
            request.url.path,
            status,
            extra={"fields": {
                "method": method,
                "path": request.url.path,
                "status": status,
                "duration_ms": round(duration * 1000, 2),
            }},
        )
        return response


app.add_middleware(MetricsMiddleware)
app.add_middleware(OpenTelemetryMiddleware)
# SPAFallback must be inside SecurityHeaders so index.html responses receive
# the CSP nonce header (and every static response gets hardening headers).
app.add_middleware(SPAFallbackMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than 50 MB (including chunked bodies)."""

    MAX_BODY_SIZE = 50 * 1024 * 1024

    class _BodyTooLarge(Exception):
        pass

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                return Response(status_code=400, content="Invalid Content-Length")
            if declared > self.MAX_BODY_SIZE:
                return Response(status_code=413, content="Request body too large")
            return await call_next(request)

        # No Content-Length (chunked / unknown): count bytes as they stream.
        if "chunked" in (request.headers.get("transfer-encoding") or "").lower():
            total = 0
            inner_receive = request.receive

            async def counting_receive() -> Message:
                nonlocal total
                message = await inner_receive()
                if message["type"] == "http.request":
                    total += len(message.get("body") or b"")
                    if total > self.MAX_BODY_SIZE:
                        raise RequestSizeLimitMiddleware._BodyTooLarge()
                return message

            try:
                return await call_next(Request(request.scope, counting_receive))
            except RequestSizeLimitMiddleware._BodyTooLarge:
                return Response(status_code=413, content="Request body too large")

        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)
# CORS: wildcard with credentials is rejected in production (validate_production_settings)
# and downgraded to non-credentialed in development.
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if settings.public_url and settings.public_url.strip() and settings.public_url.strip() not in _cors_origins:
    _cors_origins.append(settings.public_url.strip())
_cors_allow_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CSRFMiddleware, allowed_origins=_cors_origins)

# Rate limiting (Redis sliding window when REDIS_URL is set, in-memory
# fallback otherwise; see settings). Phase 35: multi-instance deployments
# get a shared limiter instead of per-process budgets.
from app.middleware.rate_limit import setup_rate_limiting

setup_rate_limiting(app)

app.include_router(auth.router)
app.include_router(sso.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(ai.router)
app.include_router(llm.router)
app.include_router(billing.router)
app.include_router(credentials.router)
app.include_router(environments.router)
app.include_router(mcp.router)
app.include_router(organizations.router)
app.include_router(workspaces.router)
app.include_router(workflows.router)
app.include_router(executions.router)
app.include_router(workflow_tests.router)
app.include_router(rag.router)
app.include_router(data_tables.router)
app.include_router(files.router)
app.include_router(files.v1_router)
app.include_router(monitoring.router)
app.include_router(nodes.router)
app.include_router(webhooks.router)
app.include_router(workflow_api.router)
app.include_router(audit.router)
app.include_router(ws.router)
app.include_router(connectors.router)
app.include_router(integrations.router)
app.include_router(code.router)
# Phase 9: live Salesforce object/field discovery (dynamic configuration).
from app.api import salesforce_discovery as salesforce_discovery_router  # noqa: E402

app.include_router(salesforce_discovery_router.router)
# Phase 10: Salesforce Outbound Message event trigger (public, no JWT).
app.include_router(salesforce_events.router)
# White-labeling and custom company branding
app.include_router(branding.router)
# Error monitoring and notifications
app.include_router(notifications.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Liveness probe — verifies process responsiveness; does NOT query dependencies."""
    # Liveness only: no dependency checks and no deployment metadata. The
    # previous hard-coded "database": "ok" was actively misleading during an
    # outage; /readyz performs the real PostgreSQL/schema/Redis checks.
    return ok({
        "status": "ok",
        "version": "1.6.0",
        "uptime_s": int(time.monotonic() - _PROCESS_START),
    })


@app.get("/readyz", tags=["health"])
@app.get("/api/readyz", tags=["health"])
def readyz() -> Any:
    """Readiness probe — returns 503 while required dependencies or startup stages are incomplete.

    Checks:
    - Lifecycle readiness (is_ready == True)
    - PostgreSQL connectivity & schema migration state (verify_schema_state)
    - Redis connectivity when configured
    """
    from fastapi.responses import JSONResponse

    from app.db import get_engine, verify_schema_state
    from app.lifecycle import get_lifecycle
    from app.security.redis_client import get_shared_redis

    lc = get_lifecycle()
    checks: dict[str, str] = {}
    ready = lc.is_ready

    if not ready:
        checks["lifecycle"] = f"not_ready ({lc.current_stage.value})"

    # 1. Database & Schema State
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(select(1))
        checks["postgres"] = "ok"

        schema_info = verify_schema_state(eng)
        if schema_info.get("ok"):
            checks["schema"] = f"ok ({schema_info.get('current_revision')})"
        else:
            checks["schema"] = f"drift_detected (current={schema_info.get('current_revision')}, expected={schema_info.get('expected_revision')})"
            ready = False
    except Exception as exc:
        logger.warning("readyz postgres check failed: %s", exc)
        checks["postgres"] = "error"
        checks["schema"] = "error"
        ready = False

    # 2. Redis State
    needs_redis = bool(get_settings().redis_url) or get_settings().queue_backend == "redis"
    if needs_redis:
        client = get_shared_redis()
        if client is None:
            checks["redis"] = "error"
            ready = False
        else:
            try:
                client.ping()
                checks["redis"] = "ok"
            except Exception as exc:
                logger.warning("readyz redis check failed: %s", exc)
                checks["redis"] = "error"
                ready = False
    else:
        checks["redis"] = "skipped"

    payload = ok({
        "status": "ready" if ready else "not_ready",
        "stage": lc.current_stage.value,
        "checks": checks,
        "uptime_s": int(time.monotonic() - _PROCESS_START),
    })
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/metrics", tags=["metrics"], response_class=PlainTextResponse)
def metrics_endpoint(user: Any = Depends(get_metrics_user)) -> str:
    """Prometheus text format. Authenticated (Phase 23/38 audit): the
    counters include per-route traffic volumes, which an attacker could
    use for recon. Scrapers authenticate with a service user token;
    see docs/monitoring.md."""
    from app.db import get_session
    from app.metrics import render_metrics
    from app.models import WorkflowRecord

    db = get_session()
    try:
        workflows_total = db.scalar(select(func.count()).select_from(WorkflowRecord)) or 0
    finally:
        db.close()
    return render_metrics([("workflows_total", workflows_total)])


_PROCESS_START = time.monotonic()
