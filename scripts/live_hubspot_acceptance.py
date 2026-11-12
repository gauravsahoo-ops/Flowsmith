"""Live HubSpot vendor acceptance against a REAL portal.

Read-only provider-level checks: authenticate, read one contact, discover
standard + custom objects from /crm/v3/schemas, and optionally read one
record from a named custom object. No records are created or deleted.

Prerequisites:
    Copy backend/.env.hubspot-live-acceptance.example to
    backend/.env.hubspot-live-acceptance and provide either a private-app
    token or an OAuth refresh token (never printed).

Run from the repo root:
    .venv\\Scripts\\python.exe scripts\\live_hubspot_acceptance.py

Exit code 0 means every executed check passed. A missing
HUBSPOT_ACCEPTANCE_OBJECT is reported as SKIPPED, not PASS.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CREDS_FILE = BACKEND / ".env.hubspot-live-acceptance"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_credentials() -> tuple[dict[str, str], dict[str, Any]]:
    values = load_env_file(CREDS_FILE)
    private_token = values.get("HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN", "").strip()
    refresh_token = values.get("HUBSPOT_ACCEPTANCE_REFRESH_TOKEN", "").strip()
    if not private_token and not refresh_token:
        sys.exit(
            "Missing HubSpot credentials. Copy backend/.env.hubspot-live-acceptance.example "
            "to backend/.env.hubspot-live-acceptance and set "
            "HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN or HUBSPOT_ACCEPTANCE_REFRESH_TOKEN."
        )
    if refresh_token:
        client_id = values.get("HUBSPOT_ACCEPTANCE_CLIENT_ID", "").strip()
        client_secret = values.get("HUBSPOT_ACCEPTANCE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            sys.exit(
                "HUBSPOT_ACCEPTANCE_REFRESH_TOKEN requires HUBSPOT_ACCEPTANCE_CLIENT_ID "
                "and HUBSPOT_ACCEPTANCE_CLIENT_SECRET."
            )
        os.environ["HUBSPOT_CLIENT_ID"] = client_id
        os.environ["HUBSPOT_CLIENT_SECRET"] = client_secret
    if private_token:
        creds = {"private_token": private_token}
    else:
        creds = {
            "refresh_token": refresh_token,
            "oauth": True,
            "hub_id": values.get("HUBSPOT_ACCEPTANCE_HUB_ID", ""),
        }
    return values, creds


async def run_checks() -> int:
    values, creds = load_credentials()
    custom_object = values.get("HUBSPOT_ACCEPTANCE_OBJECT", "").strip()

    # Import after credential env is applied so the provider sees the app
    # client id/secret for refresh-token mode.
    from app.providers.hubspot import HubSpotProviderClient

    client = HubSpotProviderClient()
    checks: list[tuple[str, str, str]] = []

    # 1. Auth + CRM data-plane read.
    try:
        listing = await client.list_records(creds, "contacts", limit=1)
        checks.append(("credential + contacts read", "PASS", f"{listing.get('count', 0)} record(s) returned"))
    except Exception as exc:  # noqa: BLE001 - surface the vendor error safely
        checks.append(("credential + contacts read", "FAIL", str(exc)[:240]))
        print_report(checks)
        return 1

    # 2. Standard + custom object discovery.
    try:
        discovery = await client.list_object_types(creds)
        objects = discovery.get("objects") or []
        keys = {item.get("key") for item in objects}
        if "contacts" not in keys:
            checks.append(("object discovery", "FAIL", f"standard objects missing: {sorted(keys)[:5]}"))
        elif not discovery.get("custom_objects_available"):
            checks.append((
                "object discovery",
                "FAIL",
                f"custom schema scope unavailable: {discovery.get('custom_error')}",
            ))
        else:
            checks.append((
                "object discovery",
                "PASS",
                f"{len(objects)} objects ({discovery.get('custom_count', 0)} custom)",
            ))
    except Exception as exc:  # noqa: BLE001
        checks.append(("object discovery", "FAIL", str(exc)[:240]))

    # 3. Optional custom-object read.
    if custom_object:
        try:
            custom = await client.list_records(creds, custom_object, limit=1)
            checks.append((
                "custom object read",
                "PASS",
                f"{custom_object}: {custom.get('count', 0)} record(s)",
            ))
        except Exception as exc:  # noqa: BLE001
            checks.append(("custom object read", "FAIL", f"{custom_object}: {str(exc)[:200]}"))
    else:
        checks.append((
            "custom object read",
            "SKIPPED",
            "set HUBSPOT_ACCEPTANCE_OBJECT to a real custom object API name",
        ))

    print_report(checks)
    return 0 if all(status != "FAIL" for _, status, _ in checks) else 1


def print_report(checks: list[tuple[str, str, str]]) -> None:
    print("\nHubSpot live vendor acceptance")
    print("==============================")
    for name, status, detail in checks:
        print(f"{status:8} {name}: {detail}")
    failed = [name for name, status, _ in checks if status == "FAIL"]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
    else:
        print("\nAll executed checks passed.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_checks()))
