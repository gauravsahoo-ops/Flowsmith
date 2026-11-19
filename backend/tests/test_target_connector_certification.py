"""Offline certification targets for Salesforce, HubSpot, and CSV Parser.

These connectors can reach the highest certification tier that does not
require live vendor credentials: Stable native + CONTRACT_VALIDATED.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.integrations.catalog.certification_state_machine import (
    get_certification_summary,
)


TARGETS = {
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
    "csv": "CSV Parser",
    "airtable": "Airtable",
    "brevo": "Brevo",
    "clickup": "ClickUp",
    "discord": "Discord",
    "dropbox": "Dropbox",
    "freshdesk": "Freshdesk",
    "mailchimp": "Mailchimp",
    "monday": "Monday.com",
    "mongodb": "MongoDB",
    "mysql": "MySQL",
    "notion": "Notion",
    "pagerduty": "PagerDuty",
    "pipedrive": "Pipedrive",
    "quickbooks": "QuickBooks",
    "redis": "Redis",
    "servicenow": "ServiceNow",
    "shopify": "Shopify",
    "todoist": "Todoist",
    "whatsapp": "WhatsApp",
    "zendesk": "Zendesk",
}


EXPECTED_TIERS = {
    key: ("LIVE_API_VALIDATED" if key == "hubspot" else "CONTRACT_VALIDATED")
    for key in TARGETS
}


def test_target_connectors_meet_expected_tier():
    summary = get_certification_summary()
    tiers = {
        row["connector"]: row["certification"]
        for row in summary.get("connectors", [])
    }
    for key, expected in EXPECTED_TIERS.items():
        assert tiers.get(key) == expected, (
            f"{key} must be {expected}; got {tiers.get(key)!r}"
        )


def test_status_csv_reflects_offline_certification():
    csv_path = Path(__file__).resolve().parents[2] / "CONNECTORS_STATUS.csv"
    if not csv_path.exists():
        pytest.skip("CONNECTORS_STATUS.csv is not present in this checkout")

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    # These three are production-grade native connectors; the expanded set
    # includes beta connectors that still have full contract-style suites.
    stable_required = {"Salesforce", "HubSpot", "CSV Parser"}

    for name in TARGETS.values():
        expected_status = "Live API validated" if name == "HubSpot" else "Contract validated"
        native_rows = [
            row for row in rows
            if row.get("Connector Name") == name
            and row.get("Development Status") in ("Stable native", "Beta native")
        ]
        assert native_rows, f"{name} row missing from CONNECTORS_STATUS.csv"
        certified_rows = [
            row for row in native_rows
            if row.get("Testing Status") == expected_status
        ]
        assert certified_rows, (
            f"{name} is not {expected_status} in CONNECTORS_STATUS.csv"
        )
        if name in stable_required:
            assert any(
                row.get("Development Status") == "Stable native"
                for row in native_rows
            ), f"{name} must remain Stable native"
