"""Container smoke test for CI (docker job in .github/workflows/ci.yml).

Exercises a freshly started container end to end with stdlib only:
liveness, readiness, auth (register/login), and one workflow CRUD round
trip. Exits non-zero with a clear message on the first failure.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(
            {"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode() or "{}")
        except ValueError:
            payload = {}
        return exc.code, payload


def main() -> int:
    email = f"smoke_{uuid.uuid4().hex[:8]}@flowsmith.dev"

    status, health = call("GET", "/api/health")
    if status != 200 or health.get("data", {}).get("status") != "ok":
        print(f"FAIL: /api/health -> {status} {health}")
        return 1
    print("ok: liveness")

    status, ready = call("GET", "/api/readyz")
    if status != 200 or ready.get("data", {}).get("status") != "ready":
        print(f"FAIL: /api/readyz -> {status} {ready}")
        return 1
    print("ok: readiness")

    status, reg = call("POST", "/api/auth/register",
                       {"email": email, "password": "SmokeTest123!"})
    if status != 201 or not reg.get("data", {}).get("token"):
        print(f"FAIL: register -> {status} {reg}")
        return 1
    token = reg["data"]["token"]
    print("ok: register")

    status, login = call("POST", "/api/auth/login",
                         {"email": email, "password": "SmokeTest123!"})
    if status != 200 or not login.get("data", {}).get("token"):
        print(f"FAIL: login -> {status} {login}")
        return 1
    print("ok: login")

    wf = {
        "id": f"wf_smoke_{uuid.uuid4().hex[:8]}",
        "name": "ci smoke",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "transform", "type": "set_data",
             "parameters": {"fields": {"greeting": "hi"}}},
        ],
        "connections": [{"source": "trigger", "target": "transform"}],
        "settings": {},
    }
    status, created = call("POST", "/api/workflows", wf, token=token)
    if status not in (200, 201) or not created.get("data", {}).get("id"):
        print(f"FAIL: create workflow -> {status} {created}")
        return 1
    wf_id = created["data"]["id"]
    print(f"ok: create workflow {wf_id}")

    status, fetched = call("GET", f"/api/workflows/{wf_id}", token=token)
    if status != 200 or fetched.get("data", {}).get("id") != wf_id:
        print(f"FAIL: get workflow -> {status} {fetched}")
        return 1
    print("ok: get workflow")

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
