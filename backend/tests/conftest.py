"""Shared fixtures + workflow builders (spec 14: tests are the spec)."""

from __future__ import annotations

import asyncio
import os

# Must be set before any app import: API tests poll endpoints rapidly
# (execution status at 20 req/s) and would trip the per-user rate limiter.
# The middleware itself has dedicated tests that enable and exercise it.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ["QUEUE_EMBEDDED_CONSUMER"] = "true"

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.config import get_settings
get_settings.cache_clear()
from app.db import Base, init_db
from app.engine.errors import NodeCancelledError
from app.engine.node_base import BaseNode, EmptyParams, NodeContext, NodeResult
from app.nodes.registry import NODE_REGISTRY, register
from app.schemas.workflow import Connection, Workflow, WorkflowNode

# Node type used by the shared slow-node fixture below. Defined here
# (not in tests/test_api/conftest.py) so every suite shares one name;
# test_api/conftest.py re-exports it for back-compat imports.
SLOW_TYPE = "slow_test_node"

def _test_db_url() -> str:
    """Dedicated test database by default (Phase 31 hardening).

    Two safeguards:

    - Tests use ``<db>_test`` unless DATABASE_URL is pinned explicitly
      (CI does). The app (dev servers, ``python -m app.serve``,
      Playwright's spawned backend) reads the default URL and consumes
      jobs from the shared queue; against the same database a stray
      server could claim queued jobs and execute them against its own
      node registry, producing impossible failures (UNKNOWN_NODE_TYPE,
      unexpected connector errors).
    - ``localhost`` is normalized to ``127.0.0.1``: on dual-stack
      Windows machines other listeners can occupy the IPv6 loopback
      port, silently routing connections to a different PostgreSQL.
    """
    from sqlalchemy.engine import make_url

    url = make_url(get_settings().database_url)
    host = "127.0.0.1" if (url.host or "") in ("localhost", "") else url.host
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    db_name = f"{url.database}_test_{worker}" if worker else f"{url.database}_test"
    return url.set(host=host, database=db_name).render_as_string(
        hide_password=False
    )


def _test_redis_url() -> str:
    """Dedicated Redis DB for tests (db 15 by default).

    Prevents external workers (connected to production db 0) from claiming
    test jobs from the shared Redis instance.
    """
    base = os.environ.get("REDIS_URL") or get_settings().redis_url or ""
    if not base:
        return ""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    db_num = "14" if worker else "15"
    if "/" in base:
        prefix = base.rsplit("/", 1)[0]
        return f"{prefix}/{db_num}"
    return f"{base.rstrip('/')}/{db_num}"


TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("TEST_DB_URL") or _test_db_url()
_isolated_redis = _test_redis_url()
if _isolated_redis:
    os.environ["REDIS_URL"] = _isolated_redis
    get_settings.cache_clear()


def _ensure_database(url: str) -> None:
    """Create the test database when missing (local convenience)."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    try:
        import psycopg
        conn = psycopg.connect(
            host=u.host if u.host not in ("localhost", "") else "127.0.0.1",
            port=u.port or 5432,
            user=u.username or "automate",
            password=u.password or "automate",
            dbname="postgres",
            autocommit=True,
        )
    except ImportError:
        import psycopg2
        admin = u.set(database="postgres", drivername="postgresql+psycopg2")
        conn = psycopg2.connect(
            host=admin.host, port=admin.port, user=admin.username,
            password=admin.password, dbname="postgres",
        )
        conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (u.database,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def _pg_harness():
    """PostgreSQL-only test harness: schema is created once per session.

    Uses the dedicated test database (see _test_db_url); tests that touch
    the database start with an empty schema thanks to the per-test
    ``_clean_db`` truncation below.
    """
    from sqlalchemy.engine import make_url

    from app.config import get_settings as _cfg

    # Hard guard: refuse to run against the application database. This
    # once caused a full dev-data wipe when pytest was invoked from the
    # repo root (wrong rootdir → main DB resolved).
    test_db = make_url(TEST_DB_URL).database
    app_db = make_url(_cfg().database_url).database
    if os.environ.get("ALLOW_TEST_ON_MAIN_DB") != "1" and test_db == app_db:
        raise RuntimeError(
            f"Refusing to run tests against the application database '{app_db}'. "
            "The harness must target a *_test database."
        )

    from app.db import engine

    _ensure_database(TEST_DB_URL)
    init_db(TEST_DB_URL)

    # Single session-scoped cleanup engine (shared across all tests).
    # Previously a new engine was created per-test, causing massive
    # connection churn and TRUNCATE deadlocks under concurrency.
    from sqlalchemy import create_engine as _create_engine
    cleanup_eng = _create_engine(
        TEST_DB_URL,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"options": "-c lock_timeout=10000 -c statement_timeout=30000"},
    )
    yield {"cleanup_engine": cleanup_eng}
    cleanup_eng.dispose()
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db(_pg_harness):
    """Start every test against an empty database (fresh-state isolation).

    Uses a single session-scoped cleanup engine. TRUNCATE takes
    ACCESS EXCLUSIVE locks on all tables; the lock_timeout ensures we
    fail fast rather than deadlock, and exponential-backoff retries
    resolve transient contention.
    """
    import time

    cleanup_engine = _pg_harness["cleanup_engine"]
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.tables.values())

    max_retries = 10
    for attempt in range(max_retries):
        try:
            with cleanup_engine.begin() as conn:
                conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
            break
        except Exception as exc:
            exc_str = str(exc).lower()
            if any(term in exc_str for term in ("deadlock", "lock timeout", "locknotavailable", "canceling statement due to lock timeout")) and attempt < max_retries - 1:
                time.sleep(0.15 * (1.5 ** attempt))
                continue
            raise

    if _isolated_redis:
        try:
            import redis
            _rc = redis.from_url(_isolated_redis)
            _rc.flushdb()
            _rc.close()
        except Exception:
            pass
    yield


# --- test stub nodes (also proves the registry is extensible) -----------

@register
class SlackStubNode(BaseNode):
    node_type = "slack"
    display_name = "Slack (test stub)"
    version = 1
    category = "Communication"
    icon = "slack"
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(self, ctx, params, input_items):
        return NodeResult(output_items=[{**item, "sent_via": "slack"} for item in input_items])


@register
class DbStubNode(BaseNode):
    node_type = "db"
    display_name = "Database (test stub)"
    version = 1
    category = "Database"
    icon = "postgres"
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(self, ctx, params, input_items):
        return NodeResult(output_items=[{**item, "saved": True} for item in input_items])


@register
class BoomNode(BaseNode):
    """A node that always explodes --- used to test error handling."""

    node_type = "boom"
    display_name = "Boom (test stub)"
    version = 1
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(self, ctx, params, input_items):
        raise RuntimeError("kaboom")


@register
class SlowNode(BaseNode):
    """A node that sleeps past its timeout."""

    node_type = "slow"
    display_name = "Slow (test stub)"
    version = 1
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(self, ctx, params, input_items):
        await asyncio.sleep(10)  # longer than any test timeout
        return NodeResult(output_items=input_items)


# --- builders ------------------------------------------------------------

def make_node(
    node_id: str,
    node_type: str,
    parameters: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> WorkflowNode:
    return WorkflowNode(id=node_id, type=node_type, parameters=parameters or {}, settings=settings or {})


def make_workflow(
    nodes: list[WorkflowNode],
    connections: list[Connection] | None = None,
    wf_id: str = "wf_test",
) -> Workflow:
    return Workflow(id=wf_id, name="test workflow", nodes=nodes, connections=connections or [])


def conn(source: str, target: str, source_handle: str = "main", target_handle: str = "main") -> Connection:
    return Connection(source=source, sourceHandle=source_handle, target=target, targetHandle=target_handle)


@pytest.fixture
def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


# --- API test fixtures (moved up from tests/test_api/conftest.py) ---------
# WHY HERE: pytest can build duplicate collector nodes for the same
# package directory when explicit file args mix tests/ root files with
# tests/test_api/ files (verified: two `Package test_api` objects).
# FixtureDefs bind to ONE collector object, so tests under the duplicate
# subtree lose every fixture defined in tests/test_api/conftest.py
# ("fixture 'client' not found"). Package(tests) never duplicates, so
# fixtures bound here resolve for the whole suite in every invocation.
# test_api/conftest.py keeps back-compat re-exports; its own fixture
# definitions were removed so they cannot shadow these.

@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset auth rate limiters between tests to prevent cross-test exhaustion."""
    from app.api.auth import _register_limiter, _forgot_password_limiter, login_throttle
    _register_limiter.reset()
    _forgot_password_limiter.reset()
    login_throttle.reset()
    yield
    _register_limiter.reset()
    _forgot_password_limiter.reset()
    login_throttle.reset()


@pytest.fixture
def client():
    """Empty Postgres DB per test (this harness truncates before each test).

    The app import is deferred so pure-unit runs pay nothing at collection.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture
def slow_node():
    """Register a node that sleeps until cancelled (stream/cancel tests)."""

    class SlowNode(BaseNode[EmptyParams]):
        node_type = SLOW_TYPE
        display_name = "Slow (test)"
        version = 1
        description = "Hangs until cancelled."
        category = "Test"
        icon = "slow"
        parameters_schema = EmptyParams

        async def run(self, ctx: NodeContext, params: EmptyParams, input_items: list[dict[str, Any]]) -> NodeResult:
            for _ in range(200):
                if ctx.is_cancelled():
                    raise NodeCancelledError()
                await asyncio.sleep(0.05)
            return NodeResult(output_items=[{"done": True}])

    NODE_REGISTRY[SLOW_TYPE] = SlowNode
    yield SLOW_TYPE
    NODE_REGISTRY.pop(SLOW_TYPE, None)
