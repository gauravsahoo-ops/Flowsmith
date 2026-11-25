"""Seed the local Flowsmith demo environment.

Creates/updates the deterministic "Demo - Lead Intake to CRM" workflow from
docs/DEMO_PLAN_2026-11-17.md, runs it once to completion, leaves a second run
waiting for approval, and seeds the supporting demo assets.

Run against the local app (default http://127.0.0.1:8000):
    .venv\\Scripts\\python.exe scripts\\seed_demo.py

No external vendor calls are made.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

BASE = os.environ.get("FLOWSMITH_DEMO_URL", "http://127.0.0.1:8000").rstrip("/")
EMAIL = os.environ.get("FLOWSMITH_DEMO_EMAIL", "demo@flowsmith.example")
PASSWORD = os.environ.get("FLOWSMITH_DEMO_PASSWORD", "DemoP@ssw0rd1")
WORKFLOW_ID = "wf_demo_lead_intake"
WORKFLOW_NAME = "Demo - Lead Intake to CRM"
DEMO_LEAD = {
    "first_name": "Avery",
    "last_name": "Chen",
    "email": "avery.chen@example.com",
    "company": "Northwind Labs",
    "score": 86,
    "source": "website_demo",
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login_or_register(client: httpx.Client) -> tuple[str, dict]:
    response = client.post(
        "/api/auth/register", json={"email": EMAIL, "password": PASSWORD}
    )
    if response.status_code == 409:
        response = client.post(
            "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
        )
    if response.status_code not in (200, 201):
        raise SystemExit(f"demo login failed: {response.status_code} {response.text[:300]}")
    data = response.json()["data"]
    token = data["token"]
    user = data.get("user") or {}
    if response.status_code in (200, 201) and not data.get("token"):
        raise SystemExit("demo login response has no token")
    # A register response also carries a token, so either path is usable.
    login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if login.status_code == 200:
        data = login.json()["data"]
        token = data["token"]
    return token, user


def get_workspace(client: httpx.Client, token: str) -> str:
    response = client.get("/api/workspaces", headers=auth(token))
    response.raise_for_status()
    workspaces = response.json().get("data") or []
    if not workspaces:
        raise SystemExit("demo user has no workspace")
    return workspaces[0]["id"]


def conn(source: str, target: str, handle: str = "main") -> dict:
    return {
        "source": source,
        "target": target,
        "sourceHandle": handle,
        "targetHandle": "main",
    }


def demo_workflow() -> dict:
    nodes = [
        {
            "id": "trigger",
            "type": "manual_trigger",
            "position": {"x": 80, "y": 160},
            "parameters": {},
        },
        {
            "id": "lead",
            "type": "set_data",
            "position": {"x": 320, "y": 160},
            "parameters": {"mode": "replace", "fields": DEMO_LEAD},
        },
        {
            "id": "score",
            "type": "if_condition",
            "position": {"x": 560, "y": 160},
            "parameters": {
                "condition": {
                    "left": "$json.score",
                    "operator": "is greater than or equal to",
                    "right": 70,
                }
            },
        },
        {
            "id": "approval",
            "type": "human_approval",
            "position": {"x": 800, "y": 60},
            "parameters": {
                "message": "Approve CRM handoff for Avery Chen",
                "approvers": [],
                "timeout_hours": 0,
            },
        },
        {
            "id": "accepted",
            "type": "set_data",
            "position": {"x": 1040, "y": 60},
            "parameters": {
                "mode": "merge",
                "fields": {"crm_status": "accepted", "crm_record": "NW-1042"},
            },
        },
        {
            "id": "done",
            "type": "noop",
            "position": {"x": 1280, "y": 60},
            "parameters": {},
        },
        {
            "id": "nurture",
            "type": "set_data",
            "position": {"x": 800, "y": 260},
            "parameters": {
                "mode": "merge",
                "fields": {"stage": "nurture", "next_step": "follow_up_sequence"},
            },
        },
        {
            "id": "nurture_done",
            "type": "noop",
            "position": {"x": 1040, "y": 260},
            "parameters": {},
        },
    ]
    connections = [
        conn("trigger", "lead"),
        conn("lead", "score"),
        conn("score", "approval", "true"),
        conn("score", "nurture", "false"),
        conn("approval", "accepted"),
        conn("accepted", "done"),
        conn("nurture", "nurture_done"),
    ]
    return {
        "id": WORKFLOW_ID,
        "name": WORKFLOW_NAME,
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "description": "Deterministic lead-intake demo; no external calls.",
            "pinned": False,
        },
        "active": False,
    }


def upsert_workflow(client: httpx.Client, token: str) -> None:
    workflow = demo_workflow()
    existing = client.get(f"/api/workflows/{WORKFLOW_ID}", headers=auth(token))
    if existing.status_code == 200:
        current = existing.json().get("data") or {}
        if current.get("version"):
            workflow["version"] = current["version"]
        updated = client.put(
            f"/api/workflows/{WORKFLOW_ID}", json=workflow, headers=auth(token)
        )
        if updated.status_code not in (200, 201):
            raise SystemExit(f"workflow update failed: {updated.status_code} {updated.text[:300]}")
        print("workflow=updated")
    else:
        created = client.post("/api/workflows", json=workflow, headers=auth(token))
        if created.status_code not in (200, 201):
            raise SystemExit(f"workflow create failed: {created.status_code} {created.text[:300]}")
        print("workflow=created")
    client.patch(
        f"/api/workflows/{WORKFLOW_ID}/active",
        json={"active": False},
        headers=auth(token),
    )


def run_execution(client: httpx.Client, token: str, *, approve: bool) -> dict:
    response = client.post(
        f"/api/workflows/{WORKFLOW_ID}/run", json={}, headers=auth(token)
    )
    if response.status_code != 202:
        raise SystemExit(f"workflow run failed: {response.status_code} {response.text[:300]}")
    execution_id = response.json()["data"]["execution_id"]
    deadline = time.monotonic() + 90
    detail = {}
    while time.monotonic() < deadline:
        detail = client.get(
            f"/api/executions/{execution_id}", headers=auth(token)
        ).json()["data"]
        if detail["status"] in ("waiting_approval", "success", "failed", "waiting_auth"):
            break
        time.sleep(0.5)
    if detail.get("status") == "waiting_approval" and approve:
        resumed = client.post(
            f"/api/executions/{execution_id}/resume",
            json={"approved": True},
            headers=auth(token),
        )
        if resumed.status_code not in (200, 202):
            raise SystemExit(f"approval resume failed: {resumed.status_code} {resumed.text[:300]}")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            detail = client.get(
                f"/api/executions/{execution_id}", headers=auth(token)
            ).json()["data"]
            if detail["status"] in ("success", "failed", "timeout"):
                break
            time.sleep(0.5)
    trace = client.get(
        f"/api/executions/{execution_id}/trace", headers=auth(token)
    ).json()["data"]["steps"]
    print(
        f"execution={execution_id} status={detail.get('status')} "
        f"steps={len(trace)} approved={approve}"
    )
    return detail


def seed_data_table(client: httpx.Client, token: str, workspace_id: str) -> None:
    tables = client.get(
        "/api/data-tables", params={"workspace_id": workspace_id}, headers=auth(token)
    )
    table_id = None
    if tables.status_code == 200:
        for table in tables.json().get("data") or []:
            if table.get("name") == "Demo Leads":
                table_id = table.get("id")
                break
    if not table_id:
        created = client.post(
            "/api/data-tables",
            headers=auth(token),
            json={
                "workspace_id": workspace_id,
                "name": "Demo Leads",
                "description": "Sample inbound leads for the demo.",
                "columns": [
                    {"name": "Email", "type": "string", "required": True},
                    {"name": "Company", "type": "string"},
                    {"name": "Score", "type": "number"},
                    {"name": "Stage", "type": "string"},
                ],
            },
        )
        if created.status_code not in (200, 201):
            print(f"data_table=skipped ({created.status_code})")
            return
        table_id = (created.json().get("data") or {}).get("id")
        print(f"data_table=created id={table_id}")
    rows = [
        {"Email": "avery.chen@example.com", "Company": "Northwind Labs", "Score": 86, "Stage": "qualified"},
        {"Email": "jordan.lee@example.com", "Company": "Contoso", "Score": 64, "Stage": "nurture"},
        {"Email": "priya.shah@example.com", "Company": "Fabrikam", "Score": 92, "Stage": "qualified"},
    ]
    for row in rows:
        client.post(
            f"/api/data-tables/{table_id}/rows",
            headers=auth(token),
            json={"data": row},
        )
    print("data_table=seeded")


def seed_knowledge(client: httpx.Client, token: str, workspace_id: str) -> None:
    collections = client.get(
        "/api/rag/collections", params={"workspace_id": workspace_id}, headers=auth(token)
    )
    collection_id = None
    if collections.status_code == 200:
        for collection in collections.json().get("data") or []:
            if collection.get("name") == "Demo Knowledge":
                collection_id = collection.get("id")
                break
    if not collection_id:
        created = client.post(
            "/api/rag/collections",
            headers=auth(token),
            json={
                "workspace_id": workspace_id,
                "name": "Demo Knowledge",
                "description": "Account notes used by the demo RAG surface.",
            },
        )
        if created.status_code not in (200, 201):
            print(f"knowledge_collection=skipped ({created.status_code})")
            return
        collection_id = (created.json().get("data") or {}).get("id")
        print(f"knowledge_collection=created id={collection_id}")
    ingest = client.post(
        f"/api/rag/collections/{collection_id}/documents",
        headers=auth(token),
        timeout=120.0,
        json={
            "documents": [
                {
                    "text": (
                        "Northwind Labs is a strategic account. Avery Chen is the "
                        "VP of Operations and prefers email. The account scored 86 "
                        "in the website demo intake and should route to CRM."
                    ),
                    "metadata": {"source": "demo", "account": "Northwind Labs"},
                }
            ]
        },
    )
    if ingest.status_code in (200, 201):
        print("knowledge_collection=seeded")
    else:
        print(f"knowledge_ingest=skipped ({ingest.status_code}) {ingest.text[:160]}")


def seed_credential(client: httpx.Client, token: str) -> None:
    credentials = client.get("/api/credentials", headers=auth(token))
    if credentials.status_code == 200:
        for credential in credentials.json().get("data") or []:
            if credential.get("name") == "Demo CRM (metadata only)":
                print("credential=exists")
                return
    created = client.post(
        "/api/credentials",
        headers=auth(token),
        json={
            "name": "Demo CRM (metadata only)",
            "type": "bearer_auth",
            "data": {"token": "demo-metadata-only-token"},
        },
    )
    print(f"credential={'created' if created.status_code in (200, 201) else 'skipped'}")


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        health = client.get("/api/health")
        if health.status_code != 200:
            print(f"app_health={health.status_code}")
            return 1
        token, _user = login_or_register(client)
        workspace_id = get_workspace(client, token)
        print(f"workspace={workspace_id}")
        upsert_workflow(client, token)
        run_execution(client, token, approve=True)
        run_execution(client, token, approve=False)
        seed_data_table(client, token, workspace_id)
        seed_knowledge(client, token, workspace_id)
        seed_credential(client, token)
        approvals = client.get("/api/approvals", headers=auth(token))
        if approvals.status_code == 200:
            pending = [
                item
                for item in approvals.json().get("data") or []
                if str(item.get("status", "")).lower() == "pending"
            ]
            print(f"pending_approvals={len(pending)}")
        path = Path(os.environ.get("TEMP", ".")) / "opencode" / "demo_credentials.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{EMAIL}\n{PASSWORD}\n", encoding="utf-8")
        print(f"demo_login={EMAIL}")
        print("demo_credentials_file=%TEMP%\\opencode\\demo_credentials.txt")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
