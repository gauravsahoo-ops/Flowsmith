"""Phase 20 - Live Salesforce acceptance.

Runs the 10 acceptance tests against the REAL Salesforce org through the
entire stack (REST API -> job queue -> embedded worker -> Salesforce
provider -> org), and writes the acceptance report to
docs/ACCEPTANCE_LIVE_SALESFORCE.md.

Prerequisites:
  - backend/.env.live-acceptance with the Connected App credentials
    (copy backend/.env.live-acceptance.example; secrets never printed).
  - Run with the project venv Python from the repo root:
        .venv\\Scripts\\python.exe scripts\\live_salesforce_acceptance.py

The script boots its own API process on an isolated port + temporary
database (the real queue/worker/connector code, no stubs), exercises the
org over the real OAuth2 username-password grant, verifies writes by
re-reading the org directly, and reports PASS/FAIL per test.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.salesforce import SalesforceProviderClient  # noqa: E402

DOCS = ROOT / "docs"
CREDS_FILE = BACKEND / ".env.live-acceptance"
CREDS_TEMPLATE = BACKEND / ".env.live-acceptance.example"
PORT = int(os.environ.get("SF_ACCEPTANCE_PORT", "8765"))

EMAIL = "accept@example.com"
PASSWORD = "Accep+2026!Pass"
CRED_GOOD = "Acceptance Org (valid)"
CRED_BAD = "Acceptance Org (invalid secret)"

API_VERSION = "v63.0"

# ---------------------------------------------------------------------------
# Credentials (never printed)
# ---------------------------------------------------------------------------


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


def load_sf_credentials() -> dict[str, str]:
    values = load_env_file(CREDS_FILE)
    missing = [
        name for name in (
            "SF_ACCEPTANCE_CLIENT_ID",
            "SF_ACCEPTANCE_CLIENT_SECRET",
        ) if not values.get(name)
    ]
    if missing:
        sys.exit(
            "Missing Salesforce credentials. Copy backend/.env.live-acceptance.example "
            f"to backend/.env.live-acceptance and fill: {', '.join(missing)}"
        )
    has_password = bool(values.get("SF_ACCEPTANCE_USERNAME") and values.get("SF_ACCEPTANCE_PASSWORD"))
    has_refresh = bool(values.get("SF_ACCEPTANCE_REFRESH_TOKEN"))
    if not has_password and not has_refresh:
        sys.exit(
            "backend/.env.live-acceptance needs either SF_ACCEPTANCE_USERNAME + "
            "SF_ACCEPTANCE_PASSWORD (password grant) or SF_ACCEPTANCE_REFRESH_TOKEN "
            "(refresh-token grant)."
        )
    return {
        "instance_url": values.get("SF_ACCEPTANCE_INSTANCE_URL", "https://login.salesforce.com"),
        "client_id": values["SF_ACCEPTANCE_CLIENT_ID"],
        "client_secret": values["SF_ACCEPTANCE_CLIENT_SECRET"],
        "username": values.get("SF_ACCEPTANCE_USERNAME", ""),
        "password": values.get("SF_ACCEPTANCE_PASSWORD", ""),
        "refresh_token": values.get("SF_ACCEPTANCE_REFRESH_TOKEN", ""),
        "api_version": values.get("SF_ACCEPTANCE_API_VERSION", API_VERSION),
    }


# ---------------------------------------------------------------------------
# Server boot (isolated port + temporary database, real app code)
# ---------------------------------------------------------------------------


def _server_env(tmpdir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"sqlite:///{tmpdir / 'live_acceptance.db'}".replace("\\", "/"),
        "POSTGRES_URL": "",
        "JWT_SECRET": secrets.token_hex(32),
        "CREDENTIALS_ENCRYPTION_KEY": __import__(
            "cryptography.fernet", fromlist=["Fernet"]
        ).Fernet.generate_key().decode(),
        "HOST": "127.0.0.1",
        "PORT": str(PORT),
        "SERVE_FRONTEND": "false",
        "QUEUE_EMBEDDED_CONSUMER": "true",
        "LOG_LEVEL": "warning",
    })
    # SSRF escape hatch pass-through (used by the rehearsal mode against
    # the local stub; not needed for the real org, which is a public host).
    for var in ("SAFE_HTTP_ALLOWED_HOSTS", "SAFE_HTTP_ALLOWED_PORTS"):
        if var in env and env[var]:
            env[var] = env[var]
    return env


def spawn_server(tmpdir: Path) -> subprocess.Popen:
    python = (ROOT / ".venv" / "Scripts" / "python.exe")
    if not python.exists():
        python = Path(sys.executable)
    log = open(tmpdir / "server.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        [str(python), "-m", "app.serve"],
        cwd=str(BACKEND),
        env=_server_env(tmpdir),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc


async def wait_healthy(client: httpx.AsyncClient, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            resp = await client.get("/api/health")
            if resp.status_code == 200:
                return
            last_error = f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        await asyncio.sleep(0.25)
    raise RuntimeError(f"API did not become healthy: {last_error}")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"^[A-Za-z0-9]{15}$")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sf_node(nid: str, params: dict, credential_id: str | None) -> dict:
    node = {
        "id": nid,
        "type": "salesforce",
        "parameters": params,
        "settings": {},
    }
    if credential_id:
        node["credentials"] = {"salesforce": credential_id}
    return node


def workflow_json(wf_id: str, name: str, nodes: list[dict], connections: list[dict]) -> dict:
    return {
        "id": wf_id,
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {},
    }


def conn(source: str, target: str, source_handle: str = "main") -> dict:
    return {"source": source, "target": target, "sourceHandle": source_handle, "targetHandle": "main"}


async def register_and_login(client: httpx.AsyncClient) -> str:
    resp = await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code in (200, 201), f"register failed: {resp.status_code} {resp.text}"
    resp = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    token = resp.json()["data"]["token"]
    assert token, "no token in login response"
    return token


async def create_credential(client: httpx.AsyncClient, token: str, name: str, data: dict) -> str:
    resp = await client.post(
        "/api/credentials",
        json={"name": name, "type": "salesforce", "data": data},
        headers=auth(token),
    )
    assert resp.status_code == 201, f"credential create failed: {resp.status_code} {resp.text}"
    return resp.json()["data"]["id"]


async def save_workflow(client: httpx.AsyncClient, token: str, wf: dict) -> None:
    resp = await client.post("/api/workflows", json=wf, headers=auth(token))
    assert resp.status_code in (200, 201), f"workflow save failed: {resp.status_code} {resp.text}"


async def run_and_wait(
    client: httpx.AsyncClient, token: str, wf_id: str, timeout_s: float = 180.0
) -> tuple[str, dict, list[dict]]:
    """POST /run (expect 202), poll until terminal, return (execution_id, detail, trace steps)."""
    resp = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=auth(token))
    assert resp.status_code == 202, f"run returned {resp.status_code}: {resp.text}"
    execution_id = resp.json()["data"]["execution_id"]

    detail = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        detail = (await client.get(
            f"/api/executions/{execution_id}", headers=auth(token)
        )).json()["data"]
        if detail["status"] not in ("queued", "running", "cancelling"):
            break
        await asyncio.sleep(0.4)
    assert detail is not None and detail["status"] not in ("queued", "running", "cancelling"), (
        f"execution {execution_id} did not finish within {timeout_s:.0f}s"
    )

    trace = (await client.get(
        f"/api/executions/{execution_id}/trace", headers=auth(token)
    )).json()["data"]["steps"]
    return execution_id, detail, trace


def step(steps: list[dict], node_id: str) -> dict:
    for s in steps:
        if s.get("node_id") == node_id or s.get("node") == node_id:
            return s
    raise AssertionError(f"no trace step for node {node_id} in {[s.get('node_id') for s in steps]}")


def node_outputs(step: dict) -> list:
    return (step.get("outputs") or {}).get("main") or []


def first_output(step: dict) -> dict:
    """First main output, or {} when the step errored (never crashes)."""
    outputs = node_outputs(step)
    return outputs[0] if outputs else {}


def step_error(step: dict) -> str:
    err = step.get("error") or {}
    return json.dumps(err) if err else "none"


# ---------------------------------------------------------------------------
# Direct org verification (real provider code, real org)
# ---------------------------------------------------------------------------

def org_client() -> SalesforceProviderClient:
    return SalesforceProviderClient(api_version=API_VERSION)


async def org_seed_lead(creds: dict, email: str) -> str:
    client = org_client()
    body = await client.create_record(
        creds, "Lead",
        {"FirstName": "Acceptance", "LastName": "Seed", "Email": email, "Company": "Acceptance Seed Co"},
    )
    lead_id = body.get("id")
    assert lead_id and TOKEN_RE.match(lead_id), f"unexpected create response: {body}"
    return lead_id


async def org_get_record(creds: dict, object_name: str, record_id: str) -> dict:
    return await org_client().get_record(creds, object_name, record_id)


async def org_find_email(creds: dict, email: str) -> int:
    soql = "SELECT Id FROM Lead WHERE Email = '{0}'".format(email.replace("'", "\\'"))
    body = await org_client().query(creds, soql)
    return body.get("totalSize", 0)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------

Results = list[dict]


def new_email(label: str, n: int) -> str:
    stamp = f"{int(time.time())}{secrets.token_hex(2)}"
    return f"accept.{label}.{n}.{stamp}@example.com"


async def test_1_auth(client, token, cred_id, emails) -> dict:
    """Authentication: search node run succeeds => OAuth token acquired from the real org."""
    wf_id = f"acc_t1_{secrets.token_hex(3)}"
    search_email = emails[1]
    await save_workflow(client, token, workflow_json(
        wf_id, "T1 Authentication",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("sf", {"operation": "search", "object_name": "Lead",
                           "search_field": "Email", "search_value": search_email}, cred_id),
        ],
        [conn("trigger", "sf")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    sf_step = step(steps, "sf")
    out = first_output(sf_step)
    ok = (
        detail["status"] == "success"
        and out.get("found") is False
        and sf_step["status"] == "success"
    )
    return {
        "test": "1 - Authentication",
        "expected": "Execution succeeds; OAuth token acquired from the real org; query runs.",
        "actual": f"status={detail['status']}; search found={out.get('found')}; "
                  f"search error={step_error(sf_step)}",
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "Real login.salesforce.com token endpoint; fresh unique email not found.",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_2_search_get(client, token, cred_id, creds, emails) -> dict:
    """Search/Get: seed a lead in the org, then search by email and fetch by id in one workflow."""
    seed_id = await org_seed_lead(creds, emails[2])
    wf_id = f"acc_t2_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T2 Search/Get",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("search", {"operation": "search", "object_name": "Lead",
                               "search_field": "Email", "search_value": emails[2]}, cred_id),
            sf_node("get", {"operation": "get", "object_name": "Lead",
                            "record_id": "{{ $json.record.Id }}"}, cred_id),
        ],
        [conn("trigger", "search"), conn("search", "get")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    search_out = first_output(step(steps, "search"))
    get_step = step(steps, "get")
    get_out = first_output(get_step)
    org_record = await org_get_record(creds, "Lead", seed_id)
    ok = (
        detail["status"] == "success"
        and search_out.get("found") is True
        and get_step["status"] == "success"
        and get_out.get("record") is not None
        and org_record.get("Id") == seed_id
        and org_record.get("Email") == emails[2]
    )
    return {
        "test": "2 - Search/Get",
        "expected": "Search finds the seeded lead; Get by id returns it; the org record round-trips intact.",
        "actual": (f"status={detail['status']}; found={search_out.get('found')}; "
                   f"getStep={get_step['status']}; getRecord=present; "
                   f"orgId={org_record.get('Id')}; orgEmail={org_record.get('Email')}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": (f"Seeded lead {seed_id} created directly in the real org first; trace record "
                  "fields are capped (spec 26) so the id round-trip is verified by direct org read."),
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_3_create(client, token, cred_id, creds, emails) -> dict:
    """Create: workflow creates a Lead; the org really has it."""
    create_email = emails[3]
    wf_id = f"acc_t3_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T3 Create",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("create", {"operation": "create", "object_name": "Lead",
                               "record": {"FirstName": "Acceptance", "LastName": "T3",
                                          "Email": create_email, "Company": "Acceptance T3 Co"}}, cred_id),
        ],
        [conn("trigger", "create")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    out = first_output(step(steps, "create"))
    created_id = out.get("id")
    org_record = await org_get_record(creds, "Lead", created_id) if created_id else {}
    ok = (
        detail["status"] == "success"
        and out.get("success") is True
        and bool(created_id) and TOKEN_RE.match(str(created_id))
        and org_record.get("Email") == create_email
        and org_record.get("Company") == "Acceptance T3 Co"
    )
    return {
        "test": "3 - Create",
        "expected": "Create returns a 15-char record id; the org stores the Lead with the given fields.",
        "actual": (f"status={detail['status']}; success={out.get('success')}; id={created_id}; "
                   f"orgEmail={org_record.get('Email')}; orgCompany={org_record.get('Company')}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "Org verified by re-reading the created Lead by id.",
        "created_id": created_id,
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_4_update(client, token, cred_id, creds, emails, created_id) -> dict:
    """Update: workflow updates the T3 lead; the org really changed."""
    wf_id = f"acc_t4_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T4 Update",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("update", {"operation": "update", "object_name": "Lead",
                               "record_id": created_id,
                               "record": {"Company": "Acceptance T4 Co"}}, cred_id),
        ],
        [conn("trigger", "update")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    out = first_output(step(steps, "update"))
    org_record = await org_get_record(creds, "Lead", created_id)
    ok = (
        detail["status"] == "success"
        and out.get("success") is True
        and out.get("id") == created_id
        and org_record.get("Company") == "Acceptance T4 Co"
    )
    return {
        "test": "4 - Update",
        "expected": "Update PATCHes Company; the org returns the new value.",
        "actual": (f"status={detail['status']}; success={out.get('success')}; "
                   f"orgCompany={org_record.get('Company')}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": f"Lead {created_id} read back from the real org after the run.",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_5_search_if_update(client, token, cred_id, creds, emails, created_id) -> dict:
    """Search -> IF -> Update: found lead routed to the true branch and updated in the org."""
    wf_id = f"acc_t5_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T5 Search->IF->Update",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("search", {"operation": "search", "object_name": "Lead",
                               "search_field": "Email", "search_value": emails[3]}, cred_id),
            {"id": "if", "type": "if_condition",
             "parameters": {"condition": {"left": "$json.found", "operator": "equals", "right": True}},
             "settings": {}},
            sf_node("update", {"operation": "update", "object_name": "Lead",
                               "record_id": "{{ $json.record.Id }}",
                               "record": {"Company": "Acceptance T5 Co"}}, cred_id),
        ],
        [conn("trigger", "search"), conn("search", "if"), conn("if", "update", "true")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    search_out = first_output(step(steps, "search"))
    update_out = first_output(step(steps, "update"))
    org_record = await org_get_record(creds, "Lead", created_id)
    ok = (
        detail["status"] == "success"
        and search_out.get("found") is True
        and step(steps, "if")["status"] == "success"
        and update_out.get("success") is True
        and update_out.get("id") == created_id
        and org_record.get("Company") == "Acceptance T5 Co"
    )
    return {
        "test": "5 - Search -> IF -> Update",
        "expected": "IF routes found=true to the update; org Company becomes the new value.",
        "actual": (f"status={detail['status']}; found={search_out.get('found')}; "
                   f"updatedId={update_out.get('id')}; orgCompany={org_record.get('Company')}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "Branch taken: if=true handle; org verified by read-back.",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_6_search_if_create(client, token, cred_id, creds, emails) -> dict:
    """Search -> IF -> Create: not-found lead routed to the false branch and created in the org."""
    create_email = emails[6]
    wf_id = f"acc_t6_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T6 Search->IF->Create",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("search", {"operation": "search", "object_name": "Lead",
                               "search_field": "Email", "search_value": create_email}, cred_id),
            {"id": "if", "type": "if_condition",
             "parameters": {"condition": {"left": "$json.found", "operator": "equals", "right": True}},
             "settings": {}},
            sf_node("create", {"operation": "create", "object_name": "Lead",
                               "record": {"FirstName": "Acceptance", "LastName": "T6",
                                          "Email": create_email, "Company": "Acceptance T6 Co"}}, cred_id),
        ],
        [conn("trigger", "search"), conn("search", "if"), conn("if", "create", "false")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    search_out = first_output(step(steps, "search"))
    create_out = first_output(step(steps, "create"))
    org_count = await org_find_email(creds, create_email)
    ok = (
        detail["status"] == "success"
        and search_out.get("found") is False
        and step(steps, "if")["status"] == "success"
        and create_out.get("success") is True
        and org_count == 1
    )
    return {
        "test": "6 - Search -> IF -> Create",
        "expected": "IF routes found=false to the create; the org ends up with exactly one lead for the email.",
        "actual": (f"status={detail['status']}; found={search_out.get('found')}; "
                   f"createdId={create_out.get('id')}; orgLeadsForEmail={org_count}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "Branch taken: if=false handle; org queried by SOQL after the run.",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_7_invalid_credentials(client, token, creds, emails) -> dict:
    """Invalid credentials: the real org rejects the token request; typed AUTH_FAILED surfaces."""
    bad_creds = dict(creds)
    bad_creds["refresh_token"] = "00D_REVOKED_OR_FAKE_REFRESH_TOKEN"
    bad_id = await create_credential(client, token, CRED_BAD, bad_creds)
    wf_id = f"acc_t7_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T7 Invalid credentials",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("sf", {"operation": "search", "object_name": "Lead",
                           "search_field": "Email", "search_value": emails[7]}, bad_id),
        ],
        [conn("trigger", "sf")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    error = detail.get("error") or {}
    ok = (
        detail["status"] == "failed"
        and error.get("code") == "AUTH_FAILED"
        and not error.get("retryable", True)
    )
    return {
        "test": "7 - Invalid credentials",
        "expected": "Execution fails with a typed, non-retryable AUTH_FAILED error from the real org.",
        "actual": (f"status={detail['status']}; error={json.dumps(error)}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "Fake refresh token against login.salesforce.com; no data touched.",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_8_invalid_input(client, token, cred_id, emails) -> dict:
    """Invalid input: the real org rejects bad SOQL; typed BAD_REQUEST surfaces its message."""
    wf_id = f"acc_t8_{secrets.token_hex(3)}"
    await save_workflow(client, token, workflow_json(
        wf_id, "T8 Invalid input",
        [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            sf_node("sf", {"operation": "search", "object_name": "Lead",
                           "search_field": "NoSuchField9__c", "search_value": emails[8]}, cred_id),
        ],
        [conn("trigger", "sf")],
    ))
    execution_id, detail, steps = await run_and_wait(client, token, wf_id)
    error = detail.get("error") or {}
    ok = (
        detail["status"] == "failed"
        and error.get("code") == "BAD_REQUEST"
        and ("NoSuchField9__c" in (error.get("message") or "") or "INVALID_FIELD" in (error.get("message") or ""))
    )
    return {
        "test": "8 - Invalid input",
        "expected": "Execution fails with BAD_REQUEST carrying the org's field error.",
        "actual": (f"status={detail['status']}; error={json.dumps(error)}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": "SOQL on a nonexistent field rejected by the real org (400 INVALID_FIELD).",
        "wf_id": wf_id,
        "execution_status": detail["status"],
    }


async def test_9_history(client, token, run_log) -> dict:
    """Execution history: every run above is listed, newest first, with matching statuses."""
    expected_per_wf: dict[str, list[tuple[str, str]]] = {}
    for wf_id, execution_id, status in run_log:
        expected_per_wf.setdefault(wf_id, []).append((execution_id, status))
    for rows in expected_per_wf.values():
        rows.reverse()  # history is newest first

    ok = True
    notes: list[str] = []
    for wf_id, expected in expected_per_wf.items():
        resp = (await client.get(
            f"/api/executions?workflow_id={wf_id}&pageSize=100", headers=auth(token)
        )).json()
        rows = [(r["id"], r["status"]) for r in resp["data"]]
        if rows != expected:
            ok = False
            notes.append(f"{wf_id}: expected {expected} got {rows}")
    total = (await client.get(
        f"/api/executions?pageSize=1", headers=auth(token)
    )).json()["meta"]["total"]
    total_ok = total == len(run_log)
    ok = ok and total_ok
    return {
        "test": "9 - Execution history",
        "expected": "All runs listed per workflow, newest first, statuses/order identical.",
        "actual": f"per-workflow match={ok}; total executions listed={total}",
        "status": "PASS" if ok else "FAIL",
        "execution_id": "-",
        "notes": "; ".join(notes) if notes else "Order = reverse execution sequence (started_at DESC, id DESC).",
    }


async def test_10_worker(client, token, execution_id, tmpdir, expected_steps) -> dict:
    """Worker execution: /run returned 202 and the job row proves the worker ran it."""
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    from app.models import Execution, Job

    engine = sa.create_engine(f"sqlite:///{(tmpdir / 'live_acceptance.db')}".replace("\\", "/"))
    session = Session(engine)
    try:
        job = session.scalar(
            sa.select(Job).where(Job.execution_id == execution_id)
        )
        rec = session.get(Execution, execution_id)
        trace_len = len((await client.get(
            f"/api/executions/{execution_id}/trace", headers=auth(token)
        )).json()["data"]["steps"])
    finally:
        session.close()
        engine.dispose()

    ok = (
        job is not None
        and job.status == "done"
        and job.attempts == 1
        and rec is not None
        and rec.status == "success"
        and trace_len == expected_steps
    )
    return {
        "test": "10 - Worker execution",
        "expected": "202 async; job row done with attempts=1; execution success; trace persisted.",
        "actual": (f"job={job.status if job else None}; attempts={job.attempts if job else None}; "
                   f"execution={rec.status if rec else None}; traceSteps={trace_len}"),
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": f"Job {job.id if job else '-'} ran through the queue into the embedded worker.",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def write_report(results: Results, sf_creds: dict, execution_refs: list[str]) -> Path:
    lines = [
        "# Live Salesforce Acceptance Report (Phase 20)",
        "",
        f"- **Date (UTC):** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Environment:** real Salesforce org via {sf_creds['instance_url']} "
        f"(OAuth2 username-password grant, API {sf_creds['api_version']})",
        f"- **User:** {sf_creds['username']}",
        f"- **Stack:** REST API -> job queue -> embedded worker -> Salesforce provider (no stubs)",
        f"- **Executions:** {len(execution_refs)}",
        "",
        "| TEST | EXPECTED | ACTUAL | STATUS | EXECUTION ID | NOTES |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['test']} | {r['expected']} | {r['actual']} | **{r['status']}** | "
            f"{r['execution_id']} | {r['notes']} |"
        )
    passed = sum(1 for r in results if r["status"] == "PASS")
    lines += [
        "",
        f"**Result: {passed}/{len(results)} PASS**",
    ]
    report = DOCS / "ACCEPTANCE_LIVE_SALESFORCE.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def print_results(results: Results) -> None:
    print()
    print(f"{'TEST':<26}{'STATUS':<8}{'EXECUTION ID':<20}{'RESULT SNAPSHOT'}")
    print("-" * 100)
    for r in results:
        print(f"{r['test']:<26}{r['status']:<8}{r['execution_id']:<20}{r['actual'][:60]}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    print("-" * 100)
    print(f"TOTAL: {passed}/{len(results)} PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    sys.path.insert(0, str(BACKEND))  # runner-side `app.*` imports (org verification)
    creds = load_sf_credentials()
    tmpdir = Path(tempfile.mkdtemp(prefix="live_acceptance_"))
    proc = spawn_server(tmpdir)
    results: Results = []
    server_log_tail = ""
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=60.0) as client:
            await wait_healthy(client)
            token = await register_and_login(client)
            good_id = await create_credential(client, token, CRED_GOOD, creds)

            emails = {n: new_email("t", n) for n in range(1, 9)}
            run_log: list[tuple[str, str, str]] = []
            created_id: str | None = None

            def record(r: dict) -> None:
                run_log.append((r["wf_id"], r["execution_id"], r.get("execution_status", "unknown")))

            r = await test_1_auth(client, token, good_id, emails)
            record(r)
            results.append(r)

            r = await test_2_search_get(client, token, good_id, creds, emails)
            record(r)
            results.append(r)

            r = await test_3_create(client, token, good_id, creds, emails)
            record(r)
            created_id = r.get("created_id")
            results.append(r)

            if created_id:
                r = await test_4_update(client, token, good_id, creds, emails, created_id)
                record(r)
                results.append(r)
                r = await test_5_search_if_update(
                    client, token, good_id, creds, emails, created_id)
                record(r)
                results.append(r)
            else:
                for label, n in (("4 - Update", 4), ("5 - Search -> IF -> Update", 5)):
                    results.append({
                        "test": label,
                        "expected": "Run succeeds; org verified.",
                        "actual": "skipped: T3 did not create a lead",
                        "status": "FAIL",
                        "execution_id": "-",
                        "notes": "Dependency on T3 (create) failed.",
                    })

            r = await test_6_search_if_create(client, token, good_id, creds, emails)
            record(r)
            results.append(r)

            r = await test_7_invalid_credentials(client, token, creds, emails)
            record(r)
            results.append(r)

            r = await test_8_invalid_input(client, token, good_id, emails)
            record(r)
            results.append(r)

            results.append(await test_9_history(client, token, run_log))

            worker_exec = results[0]["execution_id"]
            results.append(await test_10_worker(
                client, token, worker_exec, tmpdir, expected_steps=2
            ))
    except Exception as exc:
        results.append({
            "test": "HARNESS",
            "expected": "All 10 tests run",
            "actual": f"harness error: {exc!r}",
            "status": "FAIL",
            "execution_id": "-",
            "notes": "See server log tail below.",
        })
        import traceback
        traceback.print_exc()
        try:
            server_log_tail = "\n".join(
                (tmpdir / "server.log").read_text(encoding="utf-8").splitlines()[-15:]
            )
        except OSError:
            pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    report_path = write_report(results, creds, [r["execution_id"] for r in results])
    print_results(results)
    if server_log_tail:
        print("\n--- server log tail ---\n" + server_log_tail)
    print(f"\nReport written to {report_path}")
    return 0 if all(r["status"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
