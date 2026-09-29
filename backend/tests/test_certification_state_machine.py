"""Tests for Authoritative Certification State Machine & Count Reconciliation (Phase 43).

Verifies:
1. Exact count reconciliation:
   total_connectors == (
       production_certified +
       live_api_validated +
       contract_validated +
       mock_validated +
       static_validated
   )
2. State transition rules and promotion gate integrity.
3. No connector skips certification tiers.
"""

from __future__ import annotations

import pytest

from app.connectors import get_registry, register_builtin_connectors
from app.integrations.catalog.certification_state_machine import (
    CertificationState,
    AvailabilityState,
    STATE_ORDER,
    VALID_TRANSITIONS,
    compute_schema_hash,
    evaluate_promotion,
    get_certification_summary,
)


@pytest.fixture(autouse=True)
def setup_registry():
    register_builtin_connectors()


def test_reconciled_counts_exact_mathematical_equality():
    """Verifies that all 86 registered connectors are accounted for with zero discrepancy."""
    data = get_certification_summary()
    summary = data["summary"]

    total = summary["total_connectors"]
    prod = summary["production_certified"]
    live = summary["live_api_validated"]
    contract = summary["contract_validated"]
    mock = summary["mock_validated"]
    static = summary["static_validated"]

    # Sum of disjoint levels must exactly equal total connectors
    assert total == (prod + live + contract + mock + static), (
        f"Sum mismatch: {total} != {prod} + {live} + {contract} + {mock} + {static}"
    )

    # Verify exact counts against authoritative Phase 43 baseline
    assert total == 86
    assert prod == 0, "No commercial vendor sandboxes have live credentials configured yet"
    assert live == 1, "Universal HTTP is verified against public sandbox"
    assert contract == 12, "12 connectors have comprehensive contract test suites"
    assert mock == 73, "73 connectors are verified via mock/unit schemas"
    assert static == 0

    # Availability state must be tracked orthogonally
    assert summary["live_test_unavailable"] == 85, "85 connectors are awaiting live vault/sandbox credentials"
    assert summary["blocked"] == 0
    assert summary["stale_certifications"] == 0
    assert summary["expired_certifications"] == 0


def test_every_connector_has_authoritative_certification():
    """Verifies that every connector in the ledger has a valid, known certification state."""
    data = get_certification_summary()
    valid_states = {s.value for s in CertificationState}

    for item in data["connectors"]:
        assert item["certification"] in valid_states, (
            f"Connector {item['connector']} has invalid state '{item['certification']}'"
        )
        assert item["availability"] in (AvailabilityState.PASSED.value, AvailabilityState.LIVE_TEST_UNAVAILABLE.value)
        assert "version" in item
        assert "schema_hash" in item
        assert item["schema_hash"].startswith("sha256:")


def test_state_order_is_strictly_linear():
    """Verifies the state progression order."""
    expected = [
        CertificationState.STATIC_VALIDATED,
        CertificationState.MOCK_VALIDATED,
        CertificationState.CONTRACT_VALIDATED,
        CertificationState.LIVE_API_VALIDATED,
        CertificationState.PRODUCTION_CERTIFIED,
    ]
    assert STATE_ORDER == expected


def test_valid_transitions_prevent_skipping():
    """Verifies that valid transitions only allow adjacent step progression."""
    # From STATIC can only go to STATIC or MOCK
    assert VALID_TRANSITIONS[CertificationState.STATIC_VALIDATED] == {
        CertificationState.STATIC_VALIDATED,
        CertificationState.MOCK_VALIDATED,
    }
    # From MOCK can only go to CONTRACT
    assert CertificationState.LIVE_API_VALIDATED not in VALID_TRANSITIONS[CertificationState.MOCK_VALIDATED]
    assert CertificationState.PRODUCTION_CERTIFIED not in VALID_TRANSITIONS[CertificationState.MOCK_VALIDATED]

    # From CONTRACT can only go to LIVE_API_VALIDATED
    assert CertificationState.PRODUCTION_CERTIFIED not in VALID_TRANSITIONS[CertificationState.CONTRACT_VALIDATED]


def test_schema_hash_deterministic():
    """Verifies that compute_schema_hash is reproducible and depends on version and operations."""
    reg = get_registry()
    defn = reg.get_definition("salesforce")
    assert defn is not None

    hash1 = compute_schema_hash(defn)
    hash2 = compute_schema_hash(defn)
    assert hash1 == hash2
    assert hash1.startswith("sha256:")
    assert len(hash1) == 23  # sha256: + 16 chars
