#!/usr/bin/env python3
"""Synchronize connector manifest operations with the live registry.

Usage:
    python scripts/sync_connector_manifest.py [connector_key ...]

Without keys, every connector entry is refreshed. The manifest is a generated
release artifact; this script only changes operation metadata and the summary
operation count, not certification tiers or evidence timestamps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors import get_registry, register_builtin_connectors

MANIFEST = Path(__file__).resolve().parents[2] / "docs" / "audit" / "flowsmith_connector_manifest.json"

TEST_SUITES = {
    "gmail": ["backend/tests/test_api/test_gmail.py"],
    "slack": ["backend/tests/test_api/test_slack_connector.py"],
    "outlook": ["backend/tests/test_api/test_microsoft_graph_connectors.py"],
    "msteams": ["backend/tests/test_api/test_microsoft_graph_connectors.py"],
    "hubspot": ["backend/tests/test_hubspot_pagination.py", "backend/tests/test_api/test_connector_depth_round2.py"],
    "dynamics_crm": ["backend/tests/test_dynamics_pagination.py", "backend/tests/test_api/test_connector_depth_round2.py"],
    "google_sheets": ["backend/tests/test_api/test_connector_depth_round2.py"],
    "google_drive": ["backend/tests/test_api/test_connector_depth_round2.py"],
    "google_calendar": ["backend/tests/test_api/test_connector_depth_round2.py"],
    "stripe": ["backend/tests/test_api/test_connector_depth_round2.py"],
    "salesforce": ["backend/tests/test_api/test_connector_depth_round2.py"],
    "github": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "jira": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "notion": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "mongodb": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "postgres": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "mysql": ["backend/tests/test_api/test_connector_depth_round3.py"],
    "s3": [
        "backend/tests/test_new_connectors.py",
        "backend/tests/test_api/test_connector_depth_round3.py",
    ],
    "airtable": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "asana": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "trello": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "dropbox": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "zendesk": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "discord": ["backend/tests/test_api/test_connector_depth_round4.py"],
    "shopify": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "monday": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "pipedrive": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "mailchimp": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "google_docs": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "zoom": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "calendly": ["backend/tests/test_api/test_connector_depth_round5.py"],
    "quickbooks": ["backend/tests/test_api/test_connector_depth_round6.py"],
    "xero": ["backend/tests/test_api/test_connector_depth_round6.py"],
    "servicenow": ["backend/tests/test_api/test_connector_depth_round6.py"],
    "freshdesk": ["backend/tests/test_api/test_connector_depth_round6.py"],
    "freshsales": ["backend/tests/test_api/test_connector_depth_round6.py"],
    "activecampaign": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "bigquery": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "bitbucket": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "brevo": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "clickup": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "coda": ["backend/tests/test_api/test_connector_depth_round7.py"],
    "docusign": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "sendgrid": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "zoho_crm": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "pagerduty": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "intercom": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "box": ["backend/tests/test_api/test_connector_depth_round8.py"],
    "gitlab": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "linear": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "snowflake": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "supabase": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "typeform": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "resend": ["backend/tests/test_api/test_connector_depth_round9.py"],
    "openai": ["backend/tests/test_api/test_connector_depth_round10.py"],
    "anthropic": ["backend/tests/test_api/test_connector_depth_round10.py"],
    "pinecone": ["backend/tests/test_api/test_connector_depth_round10.py"],
    "twilio": ["backend/tests/test_api/test_connector_depth_round10.py"],
    "whatsapp": ["backend/tests/test_api/test_connector_depth_round10.py"],
    "sentry": ["backend/tests/test_api/test_connector_depth_round10.py"],
}


def operation_payload(operation: Any) -> dict[str, Any]:
    props = operation.input_schema.get("properties", {})
    timeout = props.get("timeout_seconds", {})
    return {
        "operation_key": operation.operation_key,
        "display_name": operation.display_name,
        "description": operation.description,
        "retryable": operation.retryable,
        "idempotency": operation.idempotency,
        "credential_require": operation.credential_require,
        "input_schema_fields": sorted(props),
        "timeout_seconds": timeout.get("default", 30.0),
    }


def main(keys: list[str]) -> int:
    register_builtin_connectors()
    registry = get_registry()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    wanted = set(keys)
    changed = 0

    for entry in manifest.get("connectors", []):
        key = entry.get("connector_key")
        if not key or (wanted and key not in wanted):
            continue
        definition = registry.get_definition(key)
        if definition is None:
            raise SystemExit(f"connector not found in registry: {key}")
        entry["operations_count"] = len(definition.operations)
        entry["operations"] = {
            op_key: operation_payload(op)
            for op_key, op in definition.operations.items()
        }
        entry["test_suite_coverage"] = TEST_SUITES.get(
            key, entry.get("test_suite_coverage") or []
        )
        changed += 1

    manifest["summary"]["total_connector_operations"] = sum(
        int(entry.get("operations_count", 0))
        for entry in manifest.get("connectors", [])
    )
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"updated {changed} connector(s); total operations = {manifest['summary']['total_connector_operations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
