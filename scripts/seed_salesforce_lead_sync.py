"""Seed the primary Salesforce demonstration workflow into a running backend.

Creates (idempotently):
1. a demo user (register)
2. a Salesforce credential (placeholder values — replace with a real
   connected-app credential to run against a real org)
3. the "Salesforce Lead Sync" workflow:

       Manual Trigger -> Set Data -> Salesforce Search Lead
            -> IF (found?) -> YES: Update Lead / NO: Create Lead

Usage: python scripts/seed_salesforce_lead_sync.py [--base http://127.0.0.1:8000]

The workflow is created for the demo user, so log in with the printed
email/password on the frontend to see it on the canvas.

Real-Salesforce instructions are in docs/PHASE_24.md.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

DEMO_EMAIL = "demo.salesforce@example.com"
DEMO_PASSWORD = "password123"

# Placeholder credential — valid shape, but never touches a real org.
SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "REPLACE_WITH_CONSUMER_KEY",
    "client_secret": "REPLACE_WITH_CONSUMER_SECRET",
    "username": "REPLACE_WITH_USERNAME",
    "password": "REPLACE_WITH_PASSWORD_PLUS_TOKEN",
    "api_version": "v63.0",
}

WORKFLOW_ID = "wf_salesforce_lead_sync"


def lead_sync_workflow(credential_id: str) -> dict:
    return {
        "id": WORKFLOW_ID,
        "name": "Salesforce Lead Sync",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "enrich",
                "type": "set_data",
                "parameters": {
                    "mode": "merge",
                    "fields": {
                        "FirstName": "{{ $json.first_name }}",
                        "LastName": "{{ $json.last_name }}",
                        "Email": "{{ $json.email }}",
                        "Company": "{{ $json.company }}",
                        "Phone": "{{ $json.phone }}",
                        "LeadSource": "Web",
                    },
                },
            },
            {
                "id": "sf_search",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": "{{ $node.enrich.json.Email }}",
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
            {
                "id": "route",
                "type": "if_condition",
                "parameters": {
                    "condition": {"left": "$json.found", "operator": "equals", "right": True},
                },
            },
            {
                "id": "sf_update",
                "type": "salesforce",
                "parameters": {
                    "operation": "update",
                    "object_name": "Lead",
                    "record_id": "{{ $node.sf_search.json.record.Id }}",
                    "record": {
                        "Company": "{{ $node.enrich.json.Company }}",
                        "Phone": "{{ $node.enrich.json.Phone }}",
                        "LeadSource": "{{ $node.enrich.json.LeadSource }}",
                    },
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
            {
                "id": "sf_create",
                "type": "salesforce",
                "parameters": {
                    "operation": "create",
                    "object_name": "Lead",
                    "record": {
                        "FirstName": "{{ $node.enrich.json.FirstName }}",
                        "LastName": "{{ $node.enrich.json.LastName }}",
                        "Email": "{{ $node.enrich.json.Email }}",
                        "Company": "{{ $node.enrich.json.Company }}",
                        "Phone": "{{ $node.enrich.json.Phone }}",
                        "LeadSource": "{{ $node.enrich.json.LeadSource }}",
                    },
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "enrich"},
            {"source": "enrich", "target": "sf_search"},
            {"source": "sf_search", "target": "route"},
            {"source": "route", "target": "sf_update", "sourceHandle": "true"},
            {"source": "route", "target": "sf_create", "sourceHandle": "false"},
        ],
        "settings": {},
    }


def req(base: str, method: str, path: str, body=None, token=None) -> tuple[int, Any]:
    r = urllib.request.Request(f"{base}{path}", method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(r, data=data, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()) if e.headers.get_content_type() == "application/json" else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base

    status, reg = req(base, "POST", "/api/auth/register", {"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    if status == 201:
        token = reg["data"]["token"]  # type: ignore[index]
    elif status == 409:  # already registered -> log in
        status, login = req(base, "POST", "/api/auth/login", {"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        assert status == 200, f"login failed: {status} {login}"
        token = login["data"]["token"]  # type: ignore[index]
    else:
        raise SystemExit(f"register failed: {status} {reg}")

    status, cred = req(base, "POST", "/api/credentials",
                       {"name": "SF Prod (demo)", "type": "salesforce", "data": SF_DATA}, token=token)
    assert status == 201, f"credential failed: {status} {cred}"
    credential_id = cred["data"]["id"]  # type: ignore[index]

    status, wf = req(base, "POST", "/api/workflows", lead_sync_workflow(credential_id), token=token)
    assert status == 201, f"workflow failed: {status} {wf}"
    print(f"Seeded workflow {wf['data']['id']!r} ({wf['data']['name']!r}) with credential {credential_id}")
    print(f"Frontend login: {DEMO_EMAIL} / {DEMO_PASSWORD}  ->  workflow appears in the canvas")
    print("To run against REAL Salesforce: edit the 'SF Prod (demo)' credential and run")
    print("  python scripts/seed_salesforce_lead_sync.py  again (workflow is idempotent by id)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
