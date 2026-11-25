"""Phase 33 - Live HubSpot full-stack acceptance (10 tests).

Runs real HubSpot workflows through the actual Flowsmith stack: REST API ->
database job queue -> embedded worker -> HubSpot connector -> CRM v3 API.

Prerequisites:
  - backend/.env.hubspot-live-acceptance with HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN
  - A custom object named flowsmith_acceptance_test (the harness seeds a
    record if the object is empty and deletes its test records afterwards).

Run from the repository root:
    .venv\\Scripts\\python.exe scripts\\live_hubspot_full_acceptance.py
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.hubspot import HubSpotProviderClient

DOCS = ROOT / "docs"
CREDS_FILE = BACKEND / ".env.hubspot-live-acceptance"
PORT = int(os.environ.get("HUBSPOT_ACCEPTANCE_PORT", "8797"))
EMAIL = os.environ.get("HUBSPOT_ACCEPTANCE_APP_EMAIL") or (
    f"hubspot.acceptance.{secrets.token_hex(4)}@example.com"
)
PASSWORD = os.environ.get("HUBSPOT_ACCEPTANCE_APP_PASSWORD", "Acceptance-P@ssw0rd1")
CRED_GOOD = "Acceptance HubSpot (valid)"
CRED_BAD = "Acceptance HubSpot (invalid)"
OBJECT_NAME = "flowsmith_acceptance_test"


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


def load_credentials() -> dict[str, str]:
    values = load_env_file(CREDS_FILE)
    token = values.get("HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN", "").strip()
    if not token:
        sys.exit(
            "Missing HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN in "
            "backend/.env.hubspot-live-acceptance."
        )
    return {
        "private_token": token,
        "hub_id": values.get("HUBSPOT_ACCEPTANCE_HUB_ID", "248020517").strip(),
        "user": values.get("HUBSPOT_ACCEPTANCE_USER", "acceptance@example.com").strip(),
    }


def _server_env(tmpdir: Path) -> tuple[dict[str, str], str]:
    env = dict(os.environ)
    fernet_key = Fernet.generate_key().decode()
    env.update({
        "DATABASE_URL": f"sqlite:///{tmpdir / 'live_hubspot.db'}".replace("\\", "/"),
        "POSTGRES_URL": "",
        "REDIS_URL": "",
        "JWT_SECRET": secrets.token_hex(32),
        "CREDENTIALS_ENCRYPTION_KEY": fernet_key,
        "HOST": "127.0.0.1",
        "PORT": str(PORT),
        "PUBLIC_URL": f"http://127.0.0.1:{PORT}",
        "SERVE_FRONTEND": "false",
        "QUEUE_BACKEND": "db",
        "QUEUE_EMBEDDED_CONSUMER": "true",
        "LOG_LEVEL": "warning",
        "APP_ENV": "development",
    })
    return env, fernet_key


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def terminate_process_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def spawn_server(tmpdir: Path, env: dict[str, str]) -> subprocess.Popen:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    log = open(tmpdir / "server.log", "a", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(
        [str(python), "-m", "app.serve"],
        cwd=str(BACKEND),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    log.close()
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def hb_node(nid: str, params: dict, credential_id: str | None) -> dict:
    node = {
        "id": nid,
        "type": "hubspot",
        "parameters": params,
        "settings": {},
    }
    if credential_id:
        node["credentials"] = {"hubspot": credential_id}
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
    return {
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": "main",
    }


async def register_and_login(client: httpx.AsyncClient) -> str:
    resp = await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code in (200, 201), f"register failed: {resp.status_code} {resp.text}"
    resp = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    token = resp.json()["data"]["token"]
    assert token, "no token in login response"
    return token


async def create_credential(
    client: httpx.AsyncClient, token: str, name: str, data: dict
) -> str:
    resp = await client.post(
        "/api/credentials",
        json={"name": name, "type": "hubspot", "data": data},
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
    resp = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=auth(token))
    assert resp.status_code == 202, f"run returned {resp.status_code}: {resp.text}"
    execution_id = resp.json()["data"]["execution_id"]

    detail = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        detail = (
            await client.get(f"/api/executions/{execution_id}", headers=auth(token))
        ).json()["data"]
        if detail["status"] not in ("queued", "running", "cancelling"):
            break
        await asyncio.sleep(0.4)
    assert detail is not None and detail["status"] not in (
        "queued",
        "running",
        "cancelling",
    ), f"execution {execution_id} did not finish within {timeout_s:.0f}s"

    trace = (
        await client.get(f"/api/executions/{execution_id}/trace", headers=auth(token))
    ).json()["data"]["steps"]
    return execution_id, detail, trace


def step(steps: list[dict], node_id: str) -> dict:
    for item in steps:
        if item.get("node_id") == node_id or item.get("node") == node_id:
            return item
    raise AssertionError(
        f"no trace step for node {node_id} in {[s.get('node_id') for s in steps]}"
    )


def node_outputs(item: dict) -> list:
    return (item.get("outputs") or {}).get("main") or []


def first_output(item: dict) -> dict:
    outputs = node_outputs(item)
    return outputs[0] if outputs else {}


def result(
    test: str,
    expected: str,
    actual: str,
    ok: bool,
    execution_id: str,
    notes: str,
    wf_id: str,
    status: str,
) -> dict:
    return {
        "test": test,
        "expected": expected,
        "actual": actual,
        "status": "PASS" if ok else "FAIL",
        "execution_id": execution_id,
        "notes": notes,
        "wf_id": wf_id,
        "execution_status": status,
    }


async def discover_custom_object(
    provider: HubSpotProviderClient, creds: dict
) -> dict:
    discovery = await provider.list_object_types(creds)
    for item in discovery.get("objects", []):
        if item.get("is_custom") and (
            item.get("key") == OBJECT_NAME
            or OBJECT_NAME in (item.get("fully_qualified_name") or "")
        ):
            return item
    raise SystemExit(
        f"Custom object '{OBJECT_NAME}' was not found. Create it in HubSpot "
        "or set the name in the harness."
    )


async def cleanup(
    provider: HubSpotProviderClient,
    creds: dict,
    contact_id: str | None,
    custom_type: str,
) -> tuple[int, int]:
    contacts = 0
    records = 0
    failed = 0
    if contact_id:
        try:
            await provider.delete_record(creds, "contacts", contact_id)
            contacts += 1
        except Exception:  # noqa: BLE001
            failed += 1
    try:
        listing = await provider.list_records(creds, custom_type, limit=100)
        for record in listing.get("records", []):
            try:
                await provider.delete_record(creds, custom_type, record["id"])
                records += 1
            except Exception:  # noqa: BLE001
                failed += 1
    except Exception:  # noqa: BLE001
        failed += 1
    if failed:
        print(f"Cleanup warning: {failed} test record(s) could not be deleted.")
    return contacts, records


def write_report(
    results: list[dict], portal: str, cleanup_note: str
) -> Path:
    lines = [
        "# Live HubSpot Acceptance Report (Phase 33)",
        "",
        f"- **Date (UTC):** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Environment:** HubSpot portal {portal} via CRM v3 API",
        "- **Stack:** REST API -> database job queue -> embedded worker -> HubSpot connector (no stubs)",
        f"- **Executions:** {len(results)}",
        f"- **Cleanup:** {cleanup_note}",
        "",
        "| TEST | EXPECTED | ACTUAL | STATUS | EXECUTION ID | NOTES |",
        "|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['test']} | {item['expected']} | {item['actual']} | "
            f"**{item['status']}** | {item['execution_id']} | {item['notes']} |"
        )
    passed = sum(1 for item in results if item["status"] == "PASS")
    lines += ["", f"**Result: {passed}/{len(results)} PASS**"]
    report = DOCS / "ACCEPTANCE_LIVE_HUBSPOT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def print_results(results: list[dict]) -> None:
    print()
    print(f"{'TEST':<34}{'STATUS':<8}{'EXECUTION ID':<20}RESULT SNAPSHOT")
    print("-" * 110)
    for item in results:
        print(
            f"{item['test']:<34}{item['status']:<8}"
            f"{item['execution_id']:<20}{item['actual'][:60]}"
        )
    print("-" * 110)
    passed = sum(1 for item in results if item["status"] == "PASS")
    print(f"TOTAL: {passed}/{len(results)} PASS")


async def main() -> int:
    creds = load_credentials()
    if port_in_use(PORT):
        print(
            f"Port {PORT} is already in use. Stop the stale harness server "
            "or set HUBSPOT_ACCEPTANCE_PORT."
        )
        return 1
    tmpdir = Path(tempfile.mkdtemp(prefix="live_hubspot_"))
    env, _fernet_key = _server_env(tmpdir)
    proc = spawn_server(tmpdir, env)
    provider = HubSpotProviderClient()
    results: list[dict] = []
    contact_id: str | None = None
    cleanup_note = "not run"
    server_log_tail = ""
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{PORT}", timeout=60.0
        ) as client:
            await wait_healthy(client)
            token = await register_and_login(client)
            good_id = await create_credential(client, token, CRED_GOOD, creds)

            custom = await discover_custom_object(provider, creds)
            custom_type = str(custom.get("object_type_id") or custom.get("key"))
            seed = await provider.list_records(creds, custom_type, limit=1)
            if seed.get("count", 0) == 0:
                await provider.create_record(
                    creds,
                    custom_type,
                    {"name": "Flowsmith Acceptance Seed"},
                )

            stamp = f"{int(time.time())}{secrets.token_hex(3)}"
            email = f"flowsmith.acceptance.{stamp}@example.com"
            custom_name = f"Flowsmith Acceptance {stamp}"

            # 1 - Authentication + contacts read.
            wf_id = f"hub_t1_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H1 Contacts read",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {"operation": "list", "object_type": "contacts", "limit": 1}, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            direct = await provider.list_records(creds, "contacts", limit=1)
            ok = detail["status"] == "success" and out.get("count", 0) >= 1 and direct.get("count", 0) >= 1
            results.append(result(
                "1 - Authentication + contacts read",
                "Execution succeeds; contacts list returns at least one record from the real portal.",
                f"status={detail['status']}; count={out.get('count')}; direct={direct.get('count')}",
                ok, execution_id, "Real HubSpot CRM v3 list through the worker.",
                wf_id, detail["status"],
            ))
            worker_execution_id = execution_id
            worker_wf_id = wf_id

            # 2 - Object discovery.
            wf_id = f"hub_t2_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H2 Object discovery",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {"operation": "list_object_types"}, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            objects = out.get("objects") or []
            keys = {item.get("key") for item in objects}
            ok = (
                detail["status"] == "success"
                and out.get("custom_objects_available") is True
                and out.get("custom_count", 0) >= 1
                and "contacts" in keys
            )
            results.append(result(
                "2 - Object discovery",
                "Standard + custom schema discovery returns contacts and the test custom object.",
                f"status={detail['status']}; objects={out.get('count')}; custom={out.get('custom_count')}; contacts={'contacts' in keys}",
                ok, execution_id, "Live /crm/v3/schemas through the connector.",
                wf_id, detail["status"],
            ))

            # 3 - Custom object read.
            wf_id = f"hub_t3_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H3 Custom object read",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {"operation": "list", "object_type": custom_type, "limit": 1}, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            ok = detail["status"] == "success" and out.get("count", 0) >= 1
            results.append(result(
                "3 - Custom object read",
                "The custom object returns at least one real record.",
                f"status={detail['status']}; object={custom_type}; count={out.get('count')}",
                ok, execution_id, "Live custom-object list through the connector.",
                wf_id, detail["status"],
            ))

            # 4 - Contact create.
            wf_id = f"hub_t4_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H4 Contact create",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {
                        "operation": "create",
                        "object_type": "contacts",
                        "properties": {
                            "email": email,
                            "firstname": "Flowsmith",
                            "lastname": "Acceptance",
                        },
                    }, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            contact_id = str(out.get("id") or "") or None
            record = {}
            if contact_id:
                got = await provider.get_record(creds, "contacts", contact_id)
                record = got.get("record") or {}
            props = record.get("properties") or {}
            ok = (
                detail["status"] == "success"
                and bool(contact_id)
                and bool(re.fullmatch(r"\d{5,}", contact_id or ""))
                and props.get("email") == email
            )
            results.append(result(
                "4 - Contact create",
                "Create returns a real contact id; the portal stores the unique email.",
                f"status={detail['status']}; id={contact_id}; email_ok={props.get('email') == email}",
                ok, execution_id, "Real contact created and re-read; deleted in cleanup.",
                wf_id, detail["status"],
            ))

            # 5 - Contact update.
            wf_id = f"hub_t5_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H5 Contact update",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {
                        "operation": "update",
                        "object_type": "contacts",
                        "record_id": contact_id,
                        "properties": {
                            "lastname": "Acceptance Updated",
                            "company": "Flowsmith QA",
                        },
                    }, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            got_resp = (
                await provider.request(
                    creds,
                    "GET",
                    f"/crm/v3/objects/contacts/{contact_id}",
                    params={"properties": "lastname,company"},
                )
                if contact_id
                else None
            )
            props = (got_resp.json().get("properties") or {}) if got_resp else {}
            ok = (
                detail["status"] == "success"
                and props.get("lastname") == "Acceptance Updated"
                and props.get("company") == "Flowsmith QA"
            )
            results.append(result(
                "5 - Contact update",
                "Update changes lastname/company and the portal returns the new values.",
                f"status={detail['status']}; lastname={props.get('lastname')}; company={props.get('company')}",
                ok, execution_id, "Real contact PATCH; verified by direct get.",
                wf_id, detail["status"],
            ))

            # 6 - Contact search.
            wf_id = f"hub_t6_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H6 Contact search",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {
                        "operation": "search",
                        "object_type": "contacts",
                        "search_field": "email",
                        "search_value": email,
                        "limit": 10,
                    }, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            found_id = (out.get("record") or {}).get("id")
            ok = detail["status"] == "success" and out.get("found") is True and found_id == contact_id
            results.append(result(
                "6 - Contact search",
                "Search by the unique email finds the created contact.",
                f"status={detail['status']}; found={out.get('found')}; id={found_id}",
                ok, execution_id, "Live CRM search through the connector.",
                wf_id, detail["status"],
            ))

            # 7 - Custom record create.
            wf_id = f"hub_t7_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H7 Custom record create",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {
                        "operation": "create",
                        "object_type": custom_type,
                        "properties": {"name": custom_name},
                    }, good_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "hb"))
            custom_record_id = str(out.get("id") or "") or None
            got_resp = (
                await provider.request(
                    creds,
                    "GET",
                    f"/crm/v3/objects/{custom_type}/{custom_record_id}",
                    params={"properties": "name"},
                )
                if custom_record_id
                else None
            )
            props = (got_resp.json().get("properties") or {}) if got_resp else {}
            ok = (
                detail["status"] == "success"
                and bool(custom_record_id)
                and props.get("name") == custom_name
            )
            results.append(result(
                "7 - Custom record create",
                "Create returns a real custom-record id; the portal stores the name.",
                f"status={detail['status']}; id={custom_record_id}; name_ok={props.get('name') == custom_name}",
                ok, execution_id, "Real custom-object record created and re-read.",
                wf_id, detail["status"],
            ))

            # 8 - Custom record update + search.
            updated_name = f"{custom_name} Updated"
            wf_id = f"hub_t8_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H8 Custom record update + search",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("upd", {
                        "operation": "update",
                        "object_type": custom_type,
                        "record_id": custom_record_id,
                        "properties": {"name": updated_name},
                    }, good_id),
                    {
                        "id": "wait",
                        "type": "wait",
                        "parameters": {"resume": "timeInterval", "amount": 10, "unit": "seconds"},
                        "settings": {},
                    },
                    hb_node("find", {
                        "operation": "search",
                        "object_type": custom_type,
                        "search_field": "name",
                        "search_value": updated_name,
                        "limit": 10,
                    }, good_id),
                ],
                [conn("trigger", "upd"), conn("upd", "wait"), conn("wait", "find")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            out = first_output(step(steps, "find"))
            found_id = (out.get("record") or {}).get("id")
            ok = (
                detail["status"] == "success"
                and out.get("found") is True
                and found_id == custom_record_id
            )
            results.append(result(
                "8 - Custom record update + search",
                "Update changes the name; a follow-up search finds the same record.",
                f"status={detail['status']}; found={out.get('found')}; id={found_id}",
                ok, execution_id, "Update -> 10s indexing wait -> search.",
                wf_id, detail["status"],
            ))

            # 9 - Invalid credentials pause.
            bad_id = await create_credential(
                client,
                token,
                CRED_BAD,
                {"private_token": "invalid_mock_token_for_bad_auth"},
            )
            wf_id = f"hub_t9_{secrets.token_hex(3)}"
            await save_workflow(client, token, workflow_json(
                wf_id, "H9 Invalid credentials",
                [
                    {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                    hb_node("hb", {"operation": "list", "object_type": "contacts", "limit": 1}, bad_id),
                ],
                [conn("trigger", "hb")],
            ))
            execution_id, detail, steps = await run_and_wait(client, token, wf_id)
            pause = detail.get("pause_state") or {}
            ok = (
                detail["status"] == "waiting_auth"
                and pause.get("type") == "auth_required"
                and pause.get("credential_id") == bad_id
                and pause.get("node_id") == "hb"
            )
            results.append(result(
                "9 - Invalid credentials",
                "Execution pauses in waiting_auth bound to the bad credential.",
                f"status={detail['status']}; pauseType={pause.get('type')}; credential={pause.get('credential_id')}; error={(detail.get('error') or {}).get('code')}",
                ok, execution_id, "Real 401 from HubSpot; the run pauses for reconnect.",
                wf_id, detail["status"],
            ))

            # 10 - Worker execution.
            import sqlalchemy as sa
            from app.models import Execution, Job
            from sqlalchemy.orm import Session

            engine = sa.create_engine(
                f"sqlite:///{(tmpdir / 'live_hubspot.db')}".replace("\\", "/")
            )
            session = Session(engine)
            try:
                job = session.scalar(
                    sa.select(Job).where(Job.execution_id == worker_execution_id)
                )
                rec = session.get(Execution, worker_execution_id)
                trace_len = len(
                    (
                        await client.get(
                            f"/api/executions/{worker_execution_id}/trace",
                            headers=auth(token),
                        )
                    ).json()["data"]["steps"]
                )
            finally:
                session.close()
                engine.dispose()
            ok = (
                job is not None
                and job.status == "done"
                and job.attempts == 1
                and rec is not None
                and rec.status == "success"
                and trace_len == 2
            )
            results.append(result(
                "10 - Worker execution",
                "202 async; job done with attempts=1; execution success; trace persisted.",
                f"job={job.status if job else None}; attempts={job.attempts if job else None}; "
                f"execution={rec.status if rec else None}; traceSteps={trace_len}",
                ok, worker_execution_id, "Job ran through the DB queue into the embedded worker.",
                worker_wf_id, rec.status if rec else "missing",
            ))

            deleted_contacts, deleted_records = await cleanup(
                provider, creds, contact_id, custom_type
            )
            cleanup_note = (
                f"deleted {deleted_contacts} test contact(s) and "
                f"{deleted_records} custom record(s)"
            )
            print(f"Cleanup: {cleanup_note}.")
    except Exception as exc:  # noqa: BLE001
        results.append({
            "test": "HARNESS",
            "expected": "All 10 tests run",
            "actual": f"harness error: {exc!r}",
            "status": "FAIL",
            "execution_id": "-",
            "notes": "See server log tail below.",
            "wf_id": "-",
            "execution_status": "missing",
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
        terminate_process_tree(proc)

    report_path = write_report(results, "248020517", cleanup_note)
    print_results(results)
    if server_log_tail:
        print("\n--- server log tail ---\n" + server_log_tail)
    print(f"\nReport written to {report_path}")
    return 0 if all(item["status"] == "PASS" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
