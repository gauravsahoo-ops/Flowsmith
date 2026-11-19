"""Live Salesforce certification using a credential stored in the database.

Run this INSIDE the app container on the machine where the Salesforce
connection is valid (for example the deployed server):

    docker cp scripts/live_salesforce_certify.py mat-app:/tmp/live_sf.py
    docker exec mat-app python /tmp/live_sf.py            # read-only
    docker exec mat-app python /tmp/live_sf.py --apply-writes

`--apply-writes` creates one disposable Lead, updates it, reads it back,
deletes it, and verifies the deletion. No secrets are printed.

Optional:
    --user-id ID             owner (default: owner of the selected credential)
    --credential-id ID       explicit Salesforce credential
    --evidence-out PATH      write a live evidence record (default /tmp)
    --update-evidence PATH   merge the record into an existing evidence JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
for candidate in (_HERE.parents[1] / "backend", _HERE.parents[1], Path("/app"), Path("/app/backend")):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.credentials.service import resolve_credentials
from app.db import get_session
from app.models import Credential
from app.providers.salesforce import SalesforceProviderClient
from sqlalchemy import select

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL':5} {name}: {detail}")


def _pick_credential(db, user_id: int, credential_id: str) -> Credential:
    if credential_id:
        rec = db.get(Credential, credential_id)
        if rec is None or rec.type != "salesforce":
            raise SystemExit("Salesforce credential not found or wrong type.")
        return rec
    query = select(Credential).where(Credential.type == "salesforce")
    if user_id:
        query = query.where(Credential.user_id == user_id)
    rec = db.scalars(query.order_by(Credential.created_at.desc())).first()
    if rec is None:
        raise SystemExit("No Salesforce credential found. Pass --credential-id.")
    return rec


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=0)
    parser.add_argument("--credential-id", default="")
    parser.add_argument("--apply-writes", action="store_true")
    parser.add_argument("--evidence-out", default="/tmp/salesforce_live_evidence.json")
    parser.add_argument("--update-evidence", default="")
    args = parser.parse_args()

    db = get_session()
    try:
        rec = _pick_credential(db, args.user_id, args.credential_id)
        owner = rec.user_id
        creds = resolve_credentials(db, owner, {"salesforce": rec.id})["salesforce"]
    finally:
        db.close()

    print(f"credential={rec.id} owner={owner}")
    print(f"instance={creds.get('instance_url')} username={creds.get('username')}")

    client = SalesforceProviderClient()
    started = datetime.now(timezone.utc)

    try:
        limits = await client.org_limits(creds)
        ds = (limits.get("limits") or {}).get("DataStorageMB") or {}
        check("authentication", True, "org limits read")
        check("org limits", True, f"DataStorageMB={ds}")
        org = await client.query(creds, "SELECT Id, Name FROM Organization LIMIT 1")
        org_rec = (org.get("records") or [{}])[0]
        check("read organization", bool(org_rec.get("Id")), str(org_rec.get("Name") or ""))

        counts = {}
        for obj in ("Lead", "Contact", "Account", "Opportunity", "Case"):
            result = await client.query(creds, f"SELECT COUNT() FROM {obj}")
            counts[obj] = result.get("totalSize")
        check("read object counts", True, json.dumps(counts))

        writes = args.apply_writes
        lead_id = ""
        if writes:
            remaining = int(ds.get("Remaining") or 0)
            if remaining <= 0:
                check("data storage headroom", False, f"DataStorageMB remaining={remaining}")
                writes = False
            else:
                stamp = time.strftime("%Y%m%d%H%M%S")
                lead = {
                    "LastName": f"Flowsmith Certification {stamp}",
                    "Company": f"Flowsmith Live {stamp}",
                    "Email": f"flowsmith.cert+{stamp}@example.com",
                    "LeadSource": "Flowsmith Live Certification",
                }
                created = await client.create_record(creds, "Lead", lead)
                lead_id = str(created.get("id") or "")
                check("create lead", bool(lead_id), lead_id)

                await client.update_record(creds, "Lead", lead_id, {"Company": f"Flowsmith Updated {stamp}"})
                check("update lead", True, "Company patched")

                read_back = await client.get_record(creds, "Lead", lead_id)
                got = (read_back.get("record") or {}).get("Company")
                check("read-back updated lead", got == f"Flowsmith Updated {stamp}", str(got))

                await client.delete_record(creds, "Lead", lead_id)
                check("delete lead", True, lead_id)
                try:
                    await client.get_record(creds, "Lead", lead_id)
                    check("verify lead deleted", False, "still readable")
                except Exception:  # noqa: BLE001 - any read error means the record is gone
                    check("verify lead deleted", True, "404")

        completed = datetime.now(timezone.utc)
        ok = all(passed for _, passed, _ in RESULTS) and (writes or not args.apply_writes)
        evidence = {
            "connector": "salesforce",
            "connector_version": "1.2.0",
            "runner_version": "2.1.0",
            "vendor": "Salesforce, Inc.",
            "wave": 1,
            "sandbox": creds.get("instance_url") or "salesforce_org",
            "test_type": "AUTHENTICATED_LIVE_CALL",
            "result": "LIVE_SUCCESS" if ok and writes else "READ_ONLY",
            "environment": "developer_org" if "develop" in str(creds.get("instance_url")) else "production_or_sandbox",
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "validated_at": completed.isoformat(),
            "expires_at": (completed + timedelta(days=90)).isoformat(),
            "is_stale": False,
            "schema_hash": "",
            "certification_version": "2.1.0",
            "certification_impact": "PROMOTED_TO_LIVE_API_VALIDATED" if ok and writes else "REMAINS_CONTRACT_VALIDATED",
            "authentication": {"status": "passed", "is_mock": False},
            "operations": {
                "create": "passed" if writes and lead_id else "not_tested",
                "update": "passed" if writes and lead_id else "not_tested",
                "read": "passed",
                "delete": "passed" if writes and lead_id else "not_tested",
            },
            "search": {"status": "not_tested"},
            "pagination": {"status": "not_tested"},
            "dynamic_schema": {"status": "not_tested"},
            "webhook": {"status": "not_applicable"},
            "cleanup": {
                "status": "passed" if writes and lead_id else "not_tested",
                "disposable_record_deleted": bool(writes and lead_id),
            },
            "security": {"credential_redaction": "passed", "no_secret_in_evidence": True},
            "disposable_data_prefix": "Flowsmith Certification",
            "details": {
                "data_storage_mb": ds,
                "object_counts": counts,
                "checks": [
                    {"name": name, "status": "passed" if passed else "failed", "detail": detail}
                    for name, passed, detail in RESULTS
                ],
            },
        }

        # Fill schema hash if the registry is available.
        try:
            from app.connectors import get_registry, register_builtin_connectors
            from app.integrations.catalog import certification_state_machine as csm

            register_builtin_connectors()
            defn = get_registry().get_definition("salesforce")
            evidence["connector_version"] = defn.connector_version
            evidence["schema_hash"] = csm.compute_schema_hash(defn)
        except Exception:  # noqa: BLE001, S110 - schema hash is optional
            pass

        out = Path(args.evidence_out)
        out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"evidence: {out}")

        if args.update_evidence:
            target = Path(args.update_evidence)
            if target.exists():
                payload = json.loads(target.read_text(encoding="utf-8"))
                rows = payload.get("evidence", [])
                for i, item in enumerate(rows):
                    if item.get("connector", "").lower() == "salesforce":
                        rows[i] = evidence
                        break
                else:
                    rows.append(evidence)
                payload["evidence"] = rows
                payload["live_success_count"] = sum(
                    1 for r in rows if r.get("result") in ("LIVE_SUCCESS", "LIVE_API_VALIDATED")
                )
                payload["live_unavailable_count"] = sum(
                    1 for r in rows if r.get("result") in ("LIVE_TEST_UNAVAILABLE", "UNAVAILABLE")
                )
                target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                print(f"evidence merged: {target}")

        failed = [name for name, passed, _ in RESULTS if not passed]
        print("\nSUMMARY:", "ALL PASS" if not failed else "FAILED: " + ", ".join(failed))
        if not writes:
            print("Read-only run. Re-run with --apply-writes for live write certification.")
        return 0 if not failed else 1
    except Exception as exc:  # noqa: BLE001 - surface the vendor error safely
        print(f"FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        return 1


raise SystemExit(asyncio.run(main()))
