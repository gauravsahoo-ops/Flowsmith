"""Regenerate CONNECTORS_STATUS.csv from the connector manifest.

The manifest is the source of truth for certification tiers. This script
preserves the existing names, descriptions, and development statuses, then
adds a unique connector key plus category, availability, live-verification
date, and notes.

Run after ``scripts/generate_connector_manifest.py``:

    .venv\\Scripts\\python.exe scripts\\generate_connectors_status_csv.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "CONNECTORS_STATUS.csv"
MANIFEST_PATH = ROOT / "docs" / "audit" / "flowsmith_connector_manifest.json"

SUMMARY_LABELS = {
    "SUMMARY",
    "Development Status",
    "Stable native",
    "Beta native",
    "Generated beta",
    "Catalog only",
    "Testing Status",
    "Mock validated",
    "Contract validated",
    "Live API validated",
    "Total connectors",
}

TIER_STATUS = {
    "LIVE_API_VALIDATED": "Live API validated",
    "CONTRACT_VALIDATED": "Contract validated",
    "MOCK_VALIDATED": "Mock validated",
}

NOTES = {
    "hubspot": "Live API CRUD, search, and associations PASS.",
    "postgres": "Live local PostgreSQL evidence.",
    "redis": "Live local Redis evidence.",
    "sqlite": "Live local SQLite evidence.",
    "s3": "Live MinIO/S3 evidence.",
    "rabbitmq": "Live local RabbitMQ declare/publish/consume PASS.",
    "mqtt": "Live local Mosquitto publish/consume PASS.",
    "http": "Live HTTP evidence.",
    "mysql": "Live local MySQL 8.4 CRUD/describe/list PASS.",
    "mongodb": "Live local MongoDB 7 CRUD/aggregate/count PASS.",
    "mssql": "Live local SQL Server 2022 CRUD/describe PASS.",
    "kafka": "Live local Apache Kafka 3.9 produce/consume/list PASS.",
    "oracle": "Live local Oracle Database Free 23ai CRUD/table_list PASS.",
    "salesforce": (
        "Live auth and reads PASS on 2026-11-19; writes blocked by org storage "
        "0/5 MB (STORAGE_LIMIT_EXCEEDED); remains Contract validated."
    ),
    "csv": "Contract validated with local CSV/TSV fixtures.",
    "netsuite": "Contract validated; no public free sandbox.",
    "aws_s3": (
        "Legacy AWS S3 entry; live evidence is recorded on "
        "AWS S3 / Object Storage (s3)."
    ),
    "rabbit_m_q": "Hidden alias of rabbitmq; live evidence is recorded on rabbitmq.",
    "hubspot_trigger": "Trigger remains mock-only; HubSpot action connector is live.",
    "postgres_trigger": "Trigger remains mock-only; PostgreSQL action connector is live.",
    "redis_trigger": "Trigger remains mock-only; Redis action connector is live.",
    "mqtt_trigger": "Trigger remains mock-only; MQTT action connector is live.",
    "rabbit_m_q_trigger": "Trigger remains mock-only; RabbitMQ action connector is live.",
}


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing {CSV_PATH}; restore the base status CSV first.")
    if not MANIFEST_PATH.exists():
        raise SystemExit(
            f"Missing {MANIFEST_PATH}; run scripts/generate_connector_manifest.py first."
        )

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        existing = list(csv.DictReader(handle))

    connector_rows = [
        row
        for row in existing
        if row.get("Connector Key")
        and row["Connector Key"] not in SUMMARY_LABELS
        and row.get("Connector Name")
        and row["Connector Name"] not in SUMMARY_LABELS
    ]
    manifest = sorted(
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["connectors"],
        key=lambda c: (c["display_name"].casefold(), c["connector_key"]),
    )
    if len(connector_rows) != len(manifest):
        raise SystemExit(
            f"row count mismatch: csv={len(connector_rows)} manifest={len(manifest)}"
        )

    output: list[list[str]] = []
    for row, connector in zip(connector_rows, manifest):
        name = row["Connector Name"]
        if name.casefold() != connector["display_name"].casefold():
            raise SystemExit(
                f"row order mismatch: {name!r} vs {connector['display_name']!r}"
            )
        expected = TIER_STATUS.get(
            connector["certification_tier"], connector["certification_tier"]
        )
        key = connector["connector_key"]

        live_verified = ""
        evidence = connector.get("evidence") or {}
        if connector["certification_tier"] == "LIVE_API_VALIDATED":
            timestamp = evidence.get("timestamp")
            live_verified = timestamp[:10] if timestamp else ""
        elif key == "salesforce":
            live_verified = "2026-11-19 (reads only)"

        output.append(
            [
                key,
                name,
                connector.get("category", ""),
                row.get("Description", ""),
                row["Development Status"],
                expected,
                connector.get("availability_status", ""),
                live_verified,
                NOTES.get(key, ""),
            ]
        )

    development_counts = Counter(row[4] for row in output)
    testing_counts = Counter(row[5] for row in output)

    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Connector Key",
                "Connector Name",
                "Category",
                "Description",
                "Development Status",
                "Testing Status",
                "Availability",
                "Live Verified",
                "Notes",
            ]
        )
        writer.writerows(output)
        writer.writerow([""] * 9)
        writer.writerow(["", "SUMMARY", "", "", "", "", "", "", ""])
        writer.writerow(["", "Development Status", "Count", "", "", "", "", "", ""])
        for label in ["Stable native", "Beta native", "Generated beta", "Catalog only"]:
            writer.writerow(["", label, development_counts.get(label, 0), "", "", "", "", "", ""])
        writer.writerow(["", "Testing Status", "Count", "", "", "", "", "", ""])
        for label in ["Mock validated", "Contract validated", "Live API validated"]:
            writer.writerow(["", label, testing_counts.get(label, 0), "", "", "", "", "", ""])
        writer.writerow(["", "Total connectors", len(output), "", "", "", "", "", ""])

    print(f"rows: {len(output)}")
    print(f"development: {dict(development_counts)}")
    print(f"testing: {dict(testing_counts)}")
    print(f"live verified dates: {sum(1 for row in output if row[7])}")


if __name__ == "__main__":
    main()
