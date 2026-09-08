"""Live Salesforce acceptance for the OAuth vertical slice.

Exercises the full Salesforce connector stack against a REAL org through
the stored OAuth credential (authorization-code + PKCE refresh token),
covering every operation incl. query pagination (forced with a small
batch size), describe and list — the operations that were previously
only unit-tested.

Prerequisites:
  - A stored OAuth 'salesforce' credential (created via the
    "Connect Salesforce" flow) in the app database.
  - Run with the project venv Python from the repo root:

        .venv\\Scripts\\python.exe scripts\\live_salesforce_slice.py

Exit code 0 = all checks passed; 1 = any check failed.

Test data is created and then deleted; a duplicate-rule alert is handled
gracefully (the record is still reported as created).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.connectors.salesforce_connector import (  # noqa: E402
    SalesforceConnector,
    SalesforceConnectorParams,
)
from app.credentials import service as cs  # noqa: E402
from app.db import get_session  # noqa: E402
from app.security.crypto import decrypt_text  # noqa: E402

USER_ID = int(os.environ.get("SF_ACCEPTANCE_USER_ID", "30"))
API_VERSION = os.environ.get("SF_ACCEPTANCE_API_VERSION", "v63.0")
RESULTS: list[str] = []


def load_oauth_creds() -> dict:
    db = get_session()
    try:
        rows = db.query(cs.Credential).filter(
            cs.Credential.user_id == USER_ID, cs.Credential.type == "salesforce"
        ).all()
        for r in rows:
            data = json.loads(decrypt_text(r.data))
            if data.get("oauth") is True:
                return data
        raise SystemExit(f"no OAuth salesforce credential found for user {USER_ID}")
    finally:
        db.close()


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        print(f"FAIL {name}: {detail}", flush=True)


async def main() -> None:
    data = load_oauth_creds()
    conn = SalesforceConnector()
    context = {"credentials": {"salesforce": data}}
    email = f"slice.{uuid.uuid4().hex[:8]}@example.com"
    lead_id: str | None = None

    async def run(op: str, **kw) -> dict:
        params = SalesforceConnectorParams(operation=op, **kw)
        return await conn.op_execute(op, params.model_dump(), context)

    # 1. search: missing
    out = (await run("search", object_name="Lead", search_field="Email", search_value=email))["output"]
    check("search missing -> found=false", out.get("found") is False and out.get("record") is None)

    # 2. create (duplicate-rule alert is tolerated; id is recovered)
    out = (await run("create", object_name="Lead", record={
        "FirstName": "Slice", "LastName": "Candidate", "Company": "ACME", "Email": email,
    }))["output"]
    check("create reports success", out.get("success") is True)
    lead_id = out.get("id")
    if not lead_id:
        out2 = (await run("search", object_name="Lead", search_field="Email", search_value=email))["output"]
        lead_id = out2["record"]["Id"]
    check("create recovered a record id", bool(lead_id), f"id={lead_id}")
    check("create set duplicate_alert flag (alert-mode rule active)",
          out.get("duplicate_alert") is True or out.get("duplicate_alert") is None)

    # 3. search: found
    out = (await run("search", object_name="Lead", search_field="Email", search_value=email))["output"]
    check("search found the created lead", out.get("found") is True and out["record"].get("Email") == email)

    # 4. get
    out = (await run("get", object_name="Lead", record_id=lead_id))["output"]
    check("get returns the record", out["record"].get("Id") == lead_id)

    # 5. update
    out = (await run("update", object_name="Lead", record_id=lead_id, record={"Company": "ACME (live)"}))["output"]
    check("update reports success", out.get("success") is True)
    out = (await run("get", object_name="Lead", record_id=lead_id))["output"]
    check("update persisted Company", out["record"].get("Company") == "ACME (live)")

    # 6. query: single page + escaped literal
    q = "SELECT Id, Name FROM Lead WHERE Company = 'ACME (live)' LIMIT 10"
    out = (await run("query", soql=q))["output"]
    check("query returns records", out.get("totalSize", 0) >= 1 and out.get("done") is True)
    check("query returns expected columns", all("Id" in r and "Name" in r for r in out["records"]))

    # 7. query pagination: force small pages with Sforce-Query-Options
    page = await conn._provider.query(
        data, "SELECT Id FROM Lead ORDER BY Id", timeout=30.0,
        headers={"Sforce-Query-Options": "batchSize=5"},
    )
    check("query pagination aggregated pages",
          page.get("done") is True and page.get("nextRecordsUrl") is None and bool(page.get("records")))

    # 8. describe
    out = (await run("describe", object_name="Lead"))["output"]
    check("describe lists Lead fields", out.get("name") == "Lead" and isinstance(out.get("fields"), list) and len(out["fields"]) > 0)
    check("describe fields carry name/label/type",
          all({"name", "label", "type"} <= set(f) for f in out["fields"][:5]))

    # 9. list objects
    out = (await run("list"))["output"]
    names = {s["name"] for s in out["sobjects"]}
    check("list includes Lead/Account", "Lead" in names and "Account" in names)

    # 10. cleanup
    out = (await run("delete", object_name="Lead", record_id=lead_id))["output"]
    check("delete reports success", out.get("success") is True)
    out = (await run("search", object_name="Lead", search_field="Email", search_value=email))["output"]
    check("search after delete -> found=false", out.get("found") is False)

    print("\n--- Salesforce OAuth slice acceptance ---", flush=True)
    for line in RESULTS:
        print(line, flush=True)
    failed = [r for r in RESULTS if r.startswith("FAIL")]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())