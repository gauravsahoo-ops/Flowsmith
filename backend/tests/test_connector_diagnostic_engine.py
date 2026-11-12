import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.connectors.diagnostic_engine import diagnose_connector, list_all_certification_tiers


@pytest.mark.asyncio
async def test_diagnose_salesforce_contract_validated():
    diag = await diagnose_connector("salesforce")
    assert diag["ok"] is True
    assert diag["connector_id"] == "salesforce"
    assert diag["certification_tier"] == "Tier 2: CONTRACT_VALIDATED"
    # SSRF enforcement is deliberately not claimed without an independent
    # outbound-policy probe; the diagnostic engine reports it as unverified.
    assert diag["ssrf_protected"] is None
    assert diag["ssrf_verification"] == "not independently verified"
    assert diag["zero_fake_success_guaranteed"] is False
    assert diag["probe_supported"] is True


@pytest.mark.asyncio
async def test_diagnose_http_live_api_validated():
    diag = await diagnose_connector("http")
    assert diag["ok"] is True
    assert diag["certification_tier"] == "Tier 1: LIVE_API_VALIDATED"


@pytest.mark.asyncio
async def test_diagnose_parity_tier_upgrade_on_successful_probe():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-ratelimit-remaining": "100"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_resp

    with patch("app.providers.jira.get_safe_http_client", return_value=mock_client):
        diag = await diagnose_connector("jira", credentials={
            "site_url": "https://jira.example.com",
            "email": "dev@example.com",
            "api_token": "live_jira_token_abc",
        })

    assert diag["ok"] is True
    # A single live probe is reachability evidence, not vendor certification.
    assert diag["certification_tier"] == "Tier 4: LIVE_PROBE_SUCCEEDED"
    assert diag["live_verified"] is True
    assert diag["diagnostic_probe"]["ok"] is True


@pytest.mark.asyncio
async def test_diagnose_probe_rejection_remediation_guide():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_resp.headers = {}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_resp

    with patch("app.providers.jira.get_safe_http_client", return_value=mock_client):
        diag = await diagnose_connector("jira", credentials={
            "site_url": "https://jira.example.com",
            "email": "dev@example.com",
            "api_token": "invalid_key",
        })

    assert diag["ok"] is True
    assert diag["live_verified"] is False
    assert "Authentication rejected" in diag["remediation_guide"]


def test_list_all_certification_tiers_catalog_integrity():
    summary = list_all_certification_tiers()
    assert summary["total_connectors"] >= 528
    assert summary["zero_fake_success_enforced"] is False
    assert summary["ssrf_firewall_enforced"] is False
    tiers = summary["tier_summary"]
    assert tiers["Tier 1: LIVE_API_VALIDATED"] >= 1
    assert tiers["Tier 2: CONTRACT_VALIDATED"] >= 10
    assert tiers["Tier 3: MOCK_VALIDATED"] >= 500
