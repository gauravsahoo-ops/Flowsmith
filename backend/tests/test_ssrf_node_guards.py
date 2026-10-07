"""Regression tests for node-level SSRF guards (S10).

Covers the audit fixes: shared ``assert_public_url`` (literal + hostname
policy + DNS resolution), rss_feed / soap_request URL validation, the
http_request delegation, and the shared execution client's redirect
re-validation hook.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext


def _ctx(**kwargs):
    return NodeContext(
        execution_id="e", workflow_id="wf", logger=logging.getLogger("t"),
        http_client=None, storage=MemoryKVStore(), **kwargs
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_settings(env: str) -> MagicMock:
    """app.config.get_settings mock with string fields _env_allowed_hosts expects."""
    m = MagicMock()
    m.app_env = env
    m.safe_http_allowed_hosts = ""
    m.safe_http_allowed_ports = ""
    return m


def _assert_denied(url: str, *, env: str = "development"):
    from app.security.ssrf import assert_public_url

    with patch("app.config.get_settings", return_value=_mock_settings(env)):
        with pytest.raises(NodeExecutionError) as exc:
            _run(assert_public_url(url, node_id="t"))
    assert exc.value.code == "SSRF_BLOCKED"
    assert exc.value.retryable is False


# ----------------------------------------------------------------------
# Shared guard
# ----------------------------------------------------------------------

def test_blocks_link_local_metadata_ip():
    _assert_denied("http://169.254.169.254/latest/meta-data/")


def test_blocks_literal_private_ipv4_and_ipv6():
    _assert_denied("http://10.0.0.5/api")
    _assert_denied("http://192.168.1.1/router")
    _assert_denied("http://[fd00::1]/x")


def test_blocks_internal_hostname_patterns():
    _assert_denied("http://metadata.google.internal/")
    _assert_denied("http://db.prod.internal/query")


def test_blocks_non_http_schemes():
    _assert_denied("ftp://example.com/f")
    _assert_denied("file:///etc/passwd")


def test_blocks_loopback_in_production():
    _assert_denied("http://127.0.0.1:8080/", env="production")
    _assert_denied("http://localhost:8080/", env="production")


def test_dev_allows_literal_loopback():
    from app.security.ssrf import assert_public_url

    with patch("app.config.get_settings", return_value=_mock_settings("development")):
        _run(assert_public_url("http://127.0.0.1:9999/hook", node_id="t"))
        _run(assert_public_url("http://localhost:9999/hook", node_id="t"))


def test_hostname_resolving_to_internal_is_blocked(monkeypatch):
    """The DNS gap: public hostname -> loopback/private target."""
    import ipaddress

    from app.security import ssrf

    async def fake_resolve(host):
        if host == "evil.example.com":
            return [ipaddress.ip_address("127.0.0.1")]
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(ssrf, "_resolve_ips", fake_resolve)
    _assert_denied("http://evil.example.com/x", env="production")
    # Dev may resolve to loopback (local stubs) but not to private ranges.
    from app.security.ssrf import assert_public_url

    with patch("app.config.get_settings", return_value=_mock_settings("development")):
        _run(assert_public_url("http://evil.example.com/x", node_id="t"))

    async def fake_private(host):
        return [ipaddress.ip_address("10.1.2.3")]

    monkeypatch.setattr(ssrf, "_resolve_ips", fake_private)
    _assert_denied("http://evil.example.com/x")


def test_env_allowlist_bypasses_policy(monkeypatch):
    from app.security import ssrf

    monkeypatch.setattr(ssrf, "_env_allowed_hosts", lambda: frozenset({"stubs.local"}))
    with patch("app.config.get_settings", return_value=_mock_settings("production")):
        _run(ssrf.assert_public_url("http://stubs.local:8181/x", node_id="t"))


# ----------------------------------------------------------------------
# Node wiring
# ----------------------------------------------------------------------

def test_rss_feed_blocks_internal_target():
    from app.nodes.rss_feed import RssFeedNode, RssFeedParams

    with pytest.raises(NodeExecutionError) as exc:
        _run(RssFeedNode().run(
            _ctx(), RssFeedParams(url="http://169.254.169.254/feed", limit=5), []
        ))
    assert exc.value.code == "SSRF_BLOCKED"
    assert exc.value.retryable is False


def test_soap_request_blocks_internal_target():
    from app.nodes.soap_request import SoapRequestNode, SoapRequestParams

    with pytest.raises(NodeExecutionError) as exc:
        _run(SoapRequestNode().run(
            _ctx(),
            SoapRequestParams(url="http://10.0.0.9/soap", action="GetStatus"),
            [],
        ))
    assert exc.value.code == "SSRF_BLOCKED"
    assert exc.value.retryable is False


def test_http_request_delegates_to_shared_guard():
    from app.nodes.http_request import HTTPRequestNode

    with pytest.raises(NodeExecutionError) as exc:
        _run(HTTPRequestNode._validate_url_ssrf("http://172.16.0.10/admin"))
    assert exc.value.code == "SSRF_BLOCKED"
    assert exc.value.retryable is False


# ----------------------------------------------------------------------
# Shared execution client: redirect re-validation hook
# ----------------------------------------------------------------------

def test_execution_client_hook_blocks_internal_targets():
    from app.runner import _ssrf_request_hook

    req = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(NodeExecutionError) as exc:
        _run(_ssrf_request_hook(req))
    assert exc.value.code == "SSRF_BLOCKED"


def test_execution_client_hook_allows_dev_loopback():
    from app.runner import _ssrf_request_hook

    with patch("app.config.get_settings", return_value=_mock_settings("development")):
        _run(_ssrf_request_hook(httpx.Request("GET", "http://127.0.0.1:8181/api")))


def test_execution_client_has_request_hook():
    from app.runner import _ssrf_request_hook, runner

    client = runner.get_http_client()
    assert _ssrf_request_hook in client.event_hooks["request"]
