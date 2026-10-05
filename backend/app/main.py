"""FastAPI application entry point (spec 17: main.py).

M9: when `serve_frontend` is enabled and the built frontend exists, the
app also serves the UI (SPA fallback to index.html) so one port runs the
whole product: UI, API, webhooks and the live WebSocket stream.
Phase 7: structured request logging + Prometheus-style metrics at
GET /api/metrics.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api import admin, ai, audit, auth, billing, branding, code, connectors, credentials, data_tables, environments, executions, files, integrations, llm, mcp, monitoring, nodes, oauth, organizations, rag, salesforce_events, sso, users, webhooks, workflow_api, workflow_tests, workflows, workspaces, ws
from app.api.auth import get_current_user
from app.api.common import ok
from app.config import get_settings
from app.db import get_session
from app.metrics import http_duration, http_requests
from app.telemetry.middleware import OpenTelemetryMiddleware

logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.config import validate_production_settings
    from app.db import get_session, init_db
    from app.maintenance import maintenance
    from app.queue.worker import ensure_embedded_consumer, stop_embedded_consumer
    from app.runner import runner
    from app.scheduler import scheduler
    from app.triggers.registry import sync_webhooks

    validate_production_settings()

    init_db()
    db = get_session()
    try:
        sync_webhooks(db)
    finally:
        db.close()
    runner.submit(scheduler.ensure_started)
    runner.submit(maintenance.ensure_started)
    ensure_embedded_consumer()
    # Register built-in connectors (connector-only node types; built-in
    # node classes always take precedence at execution time).
    from app.connectors import register_builtin_connectors

    register_builtin_connectors()

    yield

    stop_embedded_consumer()
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
app = FastAPI(title="Flowsmith API", version="0.3.1", lifespan=lifespan,
              docs_url=_docs, redoc_url=_redoc, openapi_url=_openapi)

FRONTEND_DIST: Path | None = Path(settings.frontend_dist) if settings.serve_frontend else None


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """M9: serve the built UI from the same port.

    Real files are served as-is; anything else the app 404s on falls
    back to index.html (client-side routing). /api and /ws paths are
    never touched, so router semantics (404/405/…) are preserved.
    """

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
                return FileResponse(candidate)
        response = await call_next(request)
        if (
            response.status_code == 404
            and ".." not in path
            and FRONTEND_DIST is not None
            and (FRONTEND_DIST / "index.html").is_file()
        ):
            return FileResponse(FRONTEND_DIST / "index.html")
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
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        host = request.url.hostname or ""
        if host and host not in ("127.0.0.1", "localhost", "::1"):
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
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SPAFallbackMiddleware)
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
from app.security.redis_client import get_shared_redis

setup_rate_limiting(app, redis_client=get_shared_redis())

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


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Liveness probe — does NOT fail on external dependency outages."""
    db = get_session()
    try:
        db.scalar(select(1))
        database = "ok"
    except Exception:
        database = "error"
    finally:
        db.close()
    return ok({
        "status": "ok",
        "version": "0.3.1",
        "developed_by": "Gaurav Sahoo (gauravsahoo-ops)",
        "public_url": settings.public_url,
        "uptime_s": int(time.monotonic() - _PROCESS_START),
        "database": database,
    })


@app.get("/readyz", tags=["health"])
@app.get("/api/readyz", tags=["health"])
def readyz() -> Any:
    """Readiness probe — 503 while required dependencies are unavailable.

    Checks PostgreSQL always, and Redis when the deployment is configured
    to use it (queue backend or explicit REDIS_URL). Used by Docker/K8s
    healthchecks and load-balancer readiness.
    """
    from fastapi.responses import JSONResponse

    from app.security.redis_client import get_shared_redis

    checks: dict[str, str] = {}
    ready = True

    db = get_session()
    try:
        db.scalar(select(1))
        checks["postgres"] = "ok"
    except Exception as exc:
        logger.warning("readyz postgres check failed: %s", exc)
        checks["postgres"] = "error"
        ready = False
    finally:
        db.close()

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
        "checks": checks,
        "uptime_s": int(time.monotonic() - _PROCESS_START),
    })
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/metrics", tags=["metrics"], response_class=PlainTextResponse)
def metrics_endpoint(user: Any = Depends(get_current_user)) -> str:
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
