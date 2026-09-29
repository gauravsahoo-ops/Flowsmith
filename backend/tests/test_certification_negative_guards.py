"""Required Negative Tests for Certification Promotion Gate (Phase 43).

Proves that the promotion gate REFUSES false certification under all 12 required scenarios:
1. Fake evidence (tampered hash or unknown runner)
2. Missing evidence (empty or None)
3. Expired evidence (>90 days)
4. Wrong connector name (evidence for connector A applied to connector B)
5. Wrong connector version (evidence version != registered version)
6. Missing authentication evidence (failed or mock auth)
7. Failed operation (any required operation marked failed)
8. Failed cleanup (disposable write not verified deleted)
9. Mock response presented as live
10. Manually supplied certification state (attempting to bypass runner)
11. Missing environment (e.g. environment="none")
12. Missing timestamp (invalid or absent ISO 8601 timestamps)
"""

from __future__ import annotations

import datetime
import pytest

from app.connectors import get_registry, register_builtin_connectors
from app.integrations.catalog.certification_state_machine import (
    CertificationEvidenceModel,
    CertificationState,
    compute_schema_hash,
    evaluate_promotion,
)


@pytest.fixture(autouse=True)
def setup_registry():
    register_builtin_connectors()


@pytest.fixture
def salesforce_defn():
    reg = get_registry()
    defn = reg.get_definition("salesforce")
    assert defn is not None
    return defn


@pytest.fixture
def valid_salesforce_evidence(salesforce_defn):
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    return {
        "connector": "salesforce",
        "connector_version": salesforce_defn.connector_version,
        "runner_version": "2.1.0",
        "environment": "vendor_sandbox",
        "started_at": (now - datetime.timedelta(seconds=10)).isoformat(),
        "completed_at": now_iso,
        "schema_hash": compute_schema_hash(salesforce_defn),
        "authentication": {"status": "passed", "type": "OAUTH2_REFRESH"},
        "operations": {
            "read": "passed",
            "write_disposable": "passed",
            "create": "passed",
            "get": "passed",
            "update": "passed",
            "delete": "passed",
        },
        "search": {"status": "passed", "type": "SOQL_QUERY_SEARCH"},
        "pagination": {"status": "passed", "mechanism": "URL_QUERY_CURSOR"},
        "dynamic_schema": {"status": "passed", "type": "SOBJECT_LAYOUT_DESCRIBE"},
        "webhook": {"status": "not_applicable"},
        "cleanup": {
            "status": "passed",
            "disposable_record_deleted": True,
            "disposable_id": "FLOWSMITH_CERT_TEST_123456",
        },
        "security": {
            "credential_redaction": "passed",
            "ssrf_protection": "passed",
            "no_secret_in_evidence": True,
        },
    }


# ----------------------------------------------------------------------
# 1. Fake evidence (tampered hash)
# ----------------------------------------------------------------------
def test_refuse_tampered_schema_hash(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["schema_hash"] = "sha256:forged_fake_hash_123"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("hash mismatch" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 2. Missing evidence
# ----------------------------------------------------------------------
def test_refuse_missing_evidence(salesforce_defn):
    state, reasons = evaluate_promotion({}, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("invalid evidence" in r.lower() or "missing" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 3. Expired evidence (> 90 days)
# ----------------------------------------------------------------------
def test_refuse_expired_evidence(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    old_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=95)
    evidence["started_at"] = (old_date - datetime.timedelta(minutes=1)).isoformat()
    evidence["completed_at"] = old_date.isoformat()

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("expired" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 4. Wrong connector name
# ----------------------------------------------------------------------
def test_refuse_wrong_connector(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["connector"] = "hubspot"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("mismatch" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 5. Wrong connector version
# ----------------------------------------------------------------------
def test_refuse_wrong_connector_version(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["connector_version"] = "99.9.9"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("version mismatch" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 6. Missing authentication evidence
# ----------------------------------------------------------------------
def test_refuse_failed_or_missing_auth(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["authentication"] = {"status": "failed", "error": "Invalid client secret"}

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("authentication" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 7. Failed operation in profile
# ----------------------------------------------------------------------
def test_refuse_failed_operation(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["operations"]["update"] = "failed"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("operations failed" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 8. Failed cleanup (disposable write not verified deleted)
# ----------------------------------------------------------------------
def test_refuse_failed_cleanup(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["cleanup"] = {"status": "failed", "disposable_record_deleted": False}

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("cleanup" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 9. Mock response presented as live
# ----------------------------------------------------------------------
def test_refuse_mock_response_presented_as_live(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["authentication"]["is_mock"] = True

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("mock" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 10. Manually supplied certification state
# ----------------------------------------------------------------------
def test_refuse_manually_supplied_certification_state(salesforce_defn):
    """Passing result='PRODUCTION_CERTIFIED' directly without required evidence must be rejected."""
    tampered_evidence = {
        "connector": "salesforce",
        "result": "PRODUCTION_CERTIFIED",
        "certification_state": "PRODUCTION_CERTIFIED",
    }
    state, reasons = evaluate_promotion(tampered_evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert state != CertificationState.PRODUCTION_CERTIFIED


# ----------------------------------------------------------------------
# 11. Missing environment (e.g. environment="none")
# ----------------------------------------------------------------------
def test_refuse_missing_environment(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["environment"] = "none"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("environment" in r.lower() or "invalid" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# 12. Missing or invalid timestamps
# ----------------------------------------------------------------------
def test_refuse_missing_or_invalid_timestamps(salesforce_defn, valid_salesforce_evidence):
    evidence = dict(valid_salesforce_evidence)
    evidence["completed_at"] = "not-a-timestamp"

    state, reasons = evaluate_promotion(evidence, CertificationState.CONTRACT_VALIDATED, salesforce_defn)
    assert state == CertificationState.CONTRACT_VALIDATED
    assert any("timestamp" in r.lower() or "invalid" in r.lower() for r in reasons)


# ----------------------------------------------------------------------
# Positive Control: Valid Evidence Promotes to PRODUCTION_CERTIFIED
# ----------------------------------------------------------------------
def test_positive_control_valid_evidence_promotes(salesforce_defn, valid_salesforce_evidence):
    state, reasons = evaluate_promotion(
        valid_salesforce_evidence,
        CertificationState.CONTRACT_VALIDATED,
        salesforce_defn,
    )
    assert state == CertificationState.PRODUCTION_CERTIFIED
    assert any("production certification gates passed" in r.lower() for r in reasons)
