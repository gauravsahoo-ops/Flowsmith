"""Live integration test for Universal HTTP connector (Phase 41).

Tests real execution against live public endpoints when FLOWSMITH_LIVE_TESTS=true.
"""

from __future__ import annotations

import time
import pytest

from app.connectors.http_connector import HTTPConnector
from tests.live_integrations.harness import (
    is_live_testing_enabled,
    live_registry,
)


pytestmark = [pytest.mark.live, pytest.mark.asyncio]


@pytest.fixture
def http_connector() -> HTTPConnector:
    return HTTPConnector()


@pytest.mark.asyncio
async def test_http_live_get_request(http_connector: HTTPConnector) -> None:
    """Verifies live GET request against real endpoint."""
    if not is_live_testing_enabled():
        live_registry.record(
            connector_key="http_universal",
            operation="live_get",
            status="LIVE_TEST_UNAVAILABLE",
            error_message="FLOWSMITH_LIVE_TESTS is disabled",
        )
        pytest.skip("LIVE_TEST_UNAVAILABLE: FLOWSMITH_LIVE_TESTS is disabled")

    start_t = time.time()
    try:
        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://httpbin.org/get",
                "query_params": {"test": "flowsmith_live_phase41"},
                "headers": {"User-Agent": "FlowSmith-Live-Certifier/1.0"},
                "infer_schema": True,
            },
        )
        duration_ms = (time.time() - start_t) * 1000
        assert res["success"] is True
        output = res["output"]
        assert output["status_code"] == 200
        assert output["body"]["args"]["test"] == "flowsmith_live_phase41"

        live_registry.record(
            connector_key="http_universal",
            operation="live_get",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            endpoint_called="https://httpbin.org/get",
            status_code=200,
        )
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="http_universal",
            operation="live_get",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            endpoint_called="https://httpbin.org/get",
            error_message=str(exc),
        )
        raise


@pytest.mark.asyncio
async def test_http_live_bearer_auth(http_connector: HTTPConnector) -> None:
    """Verifies live Bearer token authentication against real endpoint."""
    if not is_live_testing_enabled():
        live_registry.record(
            connector_key="http_universal",
            operation="live_bearer",
            status="LIVE_TEST_UNAVAILABLE",
            error_message="FLOWSMITH_LIVE_TESTS is disabled",
        )
        pytest.skip("LIVE_TEST_UNAVAILABLE: FLOWSMITH_LIVE_TESTS is disabled")

    start_t = time.time()
    try:
        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://httpbin.org/bearer",
                "auth_type": "bearer",
                "auth_token": "secret_live_test_token_phase41",
            },
        )
        duration_ms = (time.time() - start_t) * 1000
        assert res["success"] is True
        output = res["output"]
        assert output["status_code"] == 200
        assert output["body"]["authenticated"] is True
        assert output["body"]["token"] == "secret_live_test_token_phase41"

        live_registry.record(
            connector_key="http_universal",
            operation="live_bearer",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            endpoint_called="https://httpbin.org/bearer",
            status_code=200,
        )
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="http_universal",
            operation="live_bearer",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            endpoint_called="https://httpbin.org/bearer",
            error_message=str(exc),
        )
        raise
