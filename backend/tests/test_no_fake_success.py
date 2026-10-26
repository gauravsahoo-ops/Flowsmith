"""Guard against fabricated success responses in connectors.

The platform must never report an operation as successful when no work was
performed. This suite statically scans every connector implementation for the
patterns that previously produced fake results, and asserts that the previously
offending connectors now fail loudly instead.

Regression history:
- ``mssql_connector`` returned ``{"executed": True, "rows_affected": 1,
  "status": "success"}`` when the driver was missing or the host looked like a
  mock host.
- ``rabbitmq_connector`` returned an unflagged ``{"status": "success"}`` on
  ``ImportError``.
- ``s3_connector`` returned hardcoded ``{"status": "success"}``,
  ``{"objects": []}`` and ``{"deleted": True}`` for every operation without any
  AWS SDK call.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

CONNECTORS_DIR = Path(__file__).resolve().parents[1] / "app" / "connectors"

# Connector files that are allowed to return a literal ``success: True``:
# trigger connectors are configuration-only and label it with ``kind`` instead,
# so they are covered by the dedicated test below rather than by this scan.
#
# The scan targets the specific *fake* patterns: a success dict produced on an
# error/fallback path (ImportError handler, mock-host short-circuit).
FALLBACK_MARKERS = (
    "Executed via MSSQL abstraction",
    "Executed via RabbitMQ provider abstraction",
)


def _connector_sources() -> list[Path]:
    return sorted(CONNECTORS_DIR.glob("*_connector.py"))


def test_every_connector_file_is_parseable():
    """Sanity: the static scan must actually be able to read each connector."""
    files = _connector_sources()
    assert len(files) >= 60, f"expected the full connector suite, found {len(files)}"
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_fallback_success_notes_remain():
    """The two known fabricated-success messages must be gone."""
    offenders = []
    for path in _connector_sources():
        text = path.read_text(encoding="utf-8")
        for marker in FALLBACK_MARKERS:
            if marker in text:
                offenders.append(f"{path.name}: contains {marker!r}")
    assert not offenders, "fabricated success fallbacks found:\n" + "\n".join(offenders)


def test_no_import_error_handler_returns_success():
    """An ImportError handler must raise, never return a success payload."""
    offenders = []
    for path in _connector_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            is_import_error = (
                node.type is not None
                and isinstance(node.type, ast.Name)
                and node.type.id == "ImportError"
            )
            if not is_import_error:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    src = ast.get_source_segment(path.read_text(encoding="utf-8"), child) or ""
                    if re.search(r"success|executed|published|deleted", src, re.IGNORECASE):
                        offenders.append(f"{path.name}:{node.lineno} returns {src.strip()[:80]!r}")
    assert not offenders, "ImportError handlers must raise, not return success:\n" + "\n".join(offenders)


def test_s3_connector_derives_results_from_real_responses():
    """The S3 connector must derive every result from a real HTTP response.

    Structural check rather than a text ban: a result may only be produced after
    ``_send`` issued the request and ``_raise_for_status`` accepted the response.
    """
    source = (CONNECTORS_DIR / "s3_connector.py").read_text(encoding="utf-8")

    # There must be no literal "success" status: S3 reports the actual outcome.
    assert '"status": "success"' not in source, "S3 still returns a hardcoded success status"

    # And it must genuinely talk to S3 with signed requests.
    assert "get_safe_http_client" in source, "S3 must issue real HTTP requests"
    assert "AWS4-HMAC-SHA256" in source, "S3 must SigV4-sign requests"

    tree = ast.parse(source, filename="s3_connector.py")
    handlers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for required in ("_upload", "_download", "_list", "_delete", "_send"):
        assert required in handlers, f"S3 is missing the {required} implementation"

    # Every operation handler must go through the transport + status gate.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in ("_upload", "_download", "_list", "_delete"):
            continue
        body = ast.get_source_segment(source, node) or ""
        assert "_send(" in body, f"{node.name} never issues an HTTP request"
        assert "_raise_for_status(" in body, f"{node.name} never validates the response status"

    # No operation may short-circuit with a canned success dict before _send.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "_upload",
            "_download",
            "_list",
            "_delete",
        ):
            first_stmt = node.body[1] if len(node.body) > 1 else None  # skip docstring
            if isinstance(first_stmt, ast.Return):
                pytest.fail(f"{node.name} returns before performing any I/O")


@pytest.mark.asyncio
async def test_mssql_missing_host_raises():
    from app.connectors import ConnectorError, ConnectorErrorCode
    from app.connectors.mssql_connector import MSSQLConnector

    with pytest.raises(ConnectorError) as exc:
        await MSSQLConnector().op_execute(
            "query", {"query": "SELECT 1"}, context={"credentials": {"mssql": {}}}
        )
    assert exc.value.code == ConnectorErrorCode.NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_rabbitmq_missing_host_raises():
    from app.connectors import ConnectorError, ConnectorErrorCode
    from app.connectors.rabbitmq_connector import RabbitMQConnector

    with pytest.raises(ConnectorError) as exc:
        await RabbitMQConnector().op_execute(
            "publish", {"routing_key": "x"}, context={"credentials": {"rabbitmq": {}}}
        )
    assert exc.value.code == ConnectorErrorCode.NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_s3_missing_credentials_raises():
    from app.connectors import ConnectorError, ConnectorErrorCode
    from app.connectors.s3_connector import S3Connector

    with pytest.raises(ConnectorError) as exc:
        await S3Connector().op_execute("list_objects", {"bucket": "b"}, context={})
    assert exc.value.code == ConnectorErrorCode.NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_trigger_connectors_label_themselves_as_configuration():
    """schedule/webhook must not claim a successful remote operation."""
    from app.connectors.schedule_connector import ScheduleConnector
    from app.connectors.webhook_connector import WebhookConnector

    sched = await ScheduleConnector().op_execute("execute", {"cron": "*/5 * * * *"})
    assert sched.get("kind") == "trigger_config"
    assert sched.get("performed_outbound_call") is False
    assert "status_code" not in sched.get("output", {})

    hook = await WebhookConnector().op_execute("execute", {"path": "x"})
    assert hook.get("kind") == "trigger_config"
    assert hook.get("performed_outbound_call") is False
    assert "status_code" not in hook.get("output", {})


@pytest.mark.asyncio
async def test_every_catalog_only_connector_fails_without_endpoint():
    """Every parity/catalog connector must reject execution without a real endpoint.

    The previous generic wrapper returned a hardcoded success payload. This
    test covers the full catalog rather than a hand-picked sample.
    """
    from app.connectors import (
        ConnectorError,
        ConnectorErrorCode,
        get_registry,
        register_builtin_connectors,
    )
    from app.connectors.parity_connectors import ParityConnector

    register_builtin_connectors()
    registry = get_registry()
    catalog_only = [
        connector
        for info in registry.list_all()
        if isinstance((connector := registry.get(info.connector_id)), ParityConnector)
    ]

    assert len(catalog_only) >= 100, (
        f"expected the full catalog-only set, found {len(catalog_only)}"
    )

    for connector in catalog_only:
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute("execute", {})

        assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value, (
            f"{connector.connector_id} returned a non-configuration error: {exc_info.value}"
        )
        assert "endpoint_url" in str(exc_info.value)


@pytest.mark.asyncio
async def test_no_connector_returns_success_without_connecting():
    """Spot-check a sample of REST connectors: unconfigured -> typed error.

    Catches any future connector that replies ``success`` before it has
    credentials to work with.
    """
    from app.connectors import ConnectorError
    from app.connectors.hubspot_connector import HubSpotConnector
    from app.connectors.slack_connector import SlackConnector
    from app.connectors.zendesk_connector import ZendeskConnector

    cases = [
        (HubSpotConnector(), "search", {"object_type": "contacts", "search_field": "email", "search_value": "a@b.c"}),
        (SlackConnector(), "send_message", {"channel": "#general", "text": "hi"}),
        (ZendeskConnector(), "list_tickets", {}),
    ]
    for connector, op, payload in cases:
        with pytest.raises(ConnectorError) as exc:
            await connector.op_execute(op, payload, context={"credentials": {}})
        assert "success" not in str(exc.value).lower(), (
            f"{connector.connector_id} raised an error that claims success: {exc.value}"
        )
