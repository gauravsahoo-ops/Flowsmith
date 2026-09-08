"""Full-stack smoke test against a running instance (CI + local).

Covers the deploy story: UI served, API up, register → workflow →
manual run → webhook → execution with output.

Usage: python scripts/ci_smoke.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any


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


def wait_execution(base: str, token: str, exec_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    status = "queued"
    while time.monotonic() < deadline:
        _, ex = req(base, "GET", f"/api/executions/{exec_id}", token=token)
        status = ex["data"]["status"]  # type: ignore[index]
        if status in ("success", "failed", "cancelled"):
            return ex["data"]  # type: ignore[return-value]
        time.sleep(0.25)
    raise AssertionError(f"execution {exec_id} never finished (last status: {status})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base

    # UI + health
    r = urllib.request.Request(f"{base}/", method="GET")
    with urllib.request.urlopen(r, timeout=10) as resp:
        page = resp.read()
    assert b'id="root"' in page, "built UI not served at /"
    status, health = req(base, "GET", "/api/health")
    assert status == 200 and health["data"]["status"] == "ok", health

    # auth
    email = f"smoke_{int(time.time())}@x.com"
    _, reg = req(base, "POST", "/api/auth/register", {"email": email, "password": "password123"})
    assert reg is not None, "register failed"
    token = reg["data"]["token"]
    assert token

    # workflow: manual trigger -> set_data
    ts = int(time.time())
    wf = {
        "id": f"wf_smoke_{ts}", "name": "Smoke",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "transform", "type": "set_data", "parameters": {"fields": {"who": "{{ $json.name }}"}}},
        ],
        "connections": [{"source": "trigger", "target": "transform"}],
        "settings": {},
    }
    assert req(base, "POST", "/api/workflows", wf, token=token)[0] == 201
    _, run = req(base, "POST", f"/api/workflows/{wf['id']}/run", {"data": {"name": "ci"}}, token=token)
    assert run is not None
    data = wait_execution(base, token, run["data"]["execution_id"])
    assert data["status"] == "success", data
    assert data["results"]["outputs"]["transform"]["main"][0]["who"] == "ci", data

    # webhook trigger
    path = f"smoke-{ts}"
    hook = {
        "id": f"wf_hook_{ts}", "name": "Hook",
        "nodes": [
            {"id": "t", "type": "webhook", "parameters": {"path": path, "method": "POST"}},
            {"id": "e", "type": "set_data", "parameters": {"fields": {"msg": "{{ $json.body.msg }}"}}},
        ],
        "connections": [{"source": "t", "target": "e"}],
        "settings": {},
    }
    assert req(base, "POST", "/api/workflows", hook, token=token)[0] == 201
    assert req(base, "PATCH", f"/api/workflows/{hook['id']}/active", {"active": True}, token=token)[0] == 200
    status, hit = req(base, "POST", f"/api/webhooks/{path}", {"msg": "hi"})
    assert status == 202 and hit is not None and hit["data"]["skipped"] is False, (status, hit)
    data = wait_execution(base, token, hit["data"]["execution_id"])
    assert data["status"] == "success" and data["results"]["outputs"]["e"]["main"][0]["msg"] == "hi", data

    print("SMOKE OK: UI, health, run, webhook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
