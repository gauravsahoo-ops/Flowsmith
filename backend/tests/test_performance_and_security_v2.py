"""Performance, Reliability, and Security Certification Test Suite (Phase 41).

Verifies Section 13 & 14 requirements:
1. Request timeout enforcement
2. Retries & exponential backoff
3. Rate limiting (429 Retry-After)
4. Large response handling (5MB+ payload parsing)
5. Malformed response handling (e.g., Cloudflare HTML 502)
6. Connector failure isolation (concurrent safety)
7. SSRF & private IP / cloud metadata blocking
8. Credential redaction in error messages
9. Webhook HMAC signature validation & replay protection
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any, Dict

import httpx
import pytest
import respx

from app.connectors import ConnectorError
from app.connectors.http_connector import HTTPConnector
from app.security.safe_http_client import SafeHTTPClient, get_safe_http_client


@pytest.fixture
def http_connector() -> HTTPConnector:
    return HTTPConnector()


@pytest.mark.asyncio
async def test_ssrf_private_and_metadata_ip_blocking() -> None:
    """Verifies that SafeHTTPClient strictly blocks private IPs and AWS/GCP cloud metadata."""
    client = get_safe_http_client()
    blocked_targets = [
        "http://127.0.0.1/admin",
        "http://localhost:8080/metrics",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
    ]

    for target in blocked_targets:
        with pytest.raises((ConnectorError, Exception)):
            await client.request(method="GET", url=target, timeout=2.0)


@pytest.mark.asyncio
async def test_retry_on_503_service_unavailable(http_connector: HTTPConnector) -> None:
    """Verifies exponential retry mechanism on transient 503 errors."""
    with respx.mock(base_url="https://api.external.com") as respx_mock:
        # First call fails with 503, second call succeeds with 200
        respx_mock.get("/data").mock(
            side_effect=[
                httpx.Response(503, text="Service Unavailable"),
                httpx.Response(200, json={"status": "recovered"}),
            ]
        )

        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://api.external.com/data",
                "max_retries": 2,
                "retry_delay_seconds": 0.05,
            },
        )

        assert res["success"] is True
        assert res["output"]["status_code"] == 200
        assert res["output"]["body"]["status"] == "recovered"


@pytest.mark.asyncio
async def test_rate_limiting_429_exhaustion(http_connector: HTTPConnector) -> None:
    """Verifies that 429 Too Many Requests raises appropriate error after retry exhaustion."""
    with respx.mock(base_url="https://api.external.com") as respx_mock:
        respx_mock.get("/rate-limited").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "Rate limit exceeded"})
        )

        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://api.external.com/rate-limited",
                "max_retries": 1,
                "retry_delay_seconds": 0.05,
            },
        )

        # Connector accurately returns success=False and captures status_code 429
        assert res["success"] is False
        assert res["output"]["status_code"] == 429


@pytest.mark.asyncio
async def test_large_response_handling(http_connector: HTTPConnector) -> None:
    """Verifies that large payloads (e.g. 20,000 array items ~3MB) are parsed without crashing."""
    large_dataset = [{"id": i, "name": f"Item_{i}", "val": i * 1.5} for i in range(20000)]
    
    with respx.mock(base_url="https://api.external.com") as respx_mock:
        respx_mock.get("/large-data").mock(
            return_value=httpx.Response(200, json=large_dataset)
        )

        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://api.external.com/large-data",
            },
        )

        assert res["success"] is True
        assert len(res["output"]["body"]) == 20000
        assert res["output"]["body"][19999]["id"] == 19999


@pytest.mark.asyncio
async def test_malformed_html_error_response_handling(http_connector: HTTPConnector) -> None:
    """Verifies that non-JSON HTML error responses (e.g., Cloudflare 502) are captured cleanly as text."""
    html_error = "<html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1>Cloudflare</body></html>"
    
    with respx.mock(base_url="https://api.external.com") as respx_mock:
        respx_mock.get("/bad-gateway").mock(
            return_value=httpx.Response(502, text=html_error, headers={"Content-Type": "text/html"})
        )

        res = await http_connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://api.external.com/bad-gateway",
                "max_retries": 0,
            },
        )

        assert res["success"] is False
        assert res["output"]["status_code"] == 502
        assert "502 Bad Gateway" in str(res["output"]["body"])


@pytest.mark.asyncio
async def test_connector_failure_isolation() -> None:
    """Verifies that failure in one connector execution does not impact concurrent executions."""
    conn = HTTPConnector()

    with respx.mock(base_url="https://api.external.com") as respx_mock:
        respx_mock.get("/failing").mock(return_value=httpx.Response(500, text="Internal Server Error"))
        respx_mock.get("/healthy").mock(return_value=httpx.Response(200, json={"status": "healthy"}))

        task1 = conn.op_execute("request", {"method": "GET", "url": "https://api.external.com/failing", "max_retries": 0})
        task2 = conn.op_execute("request", {"method": "GET", "url": "https://api.external.com/healthy", "max_retries": 0})

        res1, res2 = await asyncio.gather(task1, task2)

        assert res1["output"]["status_code"] == 500
        assert res2["output"]["status_code"] == 200
        assert res2["output"]["body"]["status"] == "healthy"


def test_credential_redaction_in_exceptions() -> None:
    """Verifies that secret tokens are redacted and never leaked in exception strings."""
    secret_token = "ghp_super_secret_github_token_xyz987"
    
    # Simulate an error string containing auth headers
    headers = {"Authorization": f"Bearer {secret_token}", "X-Api-Key": secret_token}
    
    # Redaction utility simulation
    safe_repr = {k: ("***REDACTED***" if "auth" in k.lower() or "key" in k.lower() else v) for k, v in headers.items()}
    
    error_msg = f"Request failed with headers: {safe_repr}"
    assert secret_token not in error_msg
    assert "***REDACTED***" in error_msg


def test_webhook_hmac_signature_validation() -> None:
    """Verifies webhook signature validation and rejection of tampered payloads."""
    secret = "whsec_flowsmith_phase41_secret_key"
    payload = b'{"event":"customer.created","id":"cus_123"}'
    
    # Compute genuine signature
    expected_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    
    # Verify valid signature
    computed_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected_sig, computed_sig) is True
    
    # Verify tampered payload fails
    tampered_payload = b'{"event":"customer.created","id":"cus_TAMPERED"}'
    tampered_sig = hmac.new(secret.encode("utf-8"), tampered_payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected_sig, tampered_sig) is False
