"""Load-test acceptance harness (Phase 35).

Runs a realistic workflow scenario against a live stack and asserts
latency/error thresholds — the "performance" acceptance gate.

Scenario per iteration:
  POST /api/workflows/{id}/run -> poll GET /api/executions/{eid} until a
  terminal status (manual_trigger -> set_data workflow, reused).

Metrics: run end-to-end latency (submit -> terminal), poll-request
latency, error rate. Prints p50/p90/p95/p99 and exits non-zero when
thresholds are breached.

Usage (stack must be running, e.g. `python -m app.serve`):
    python scripts/loadtest.py --base http://127.0.0.1:8000 \
        --iterations 200 --concurrency 10 --p95-ms 2000 --max-error-rate 0.01
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from typing import Any

import httpx

import uuid

_WF_ID = f"wf_loadtest_{uuid.uuid4().hex[:8]}"

WORKFLOW = {
    "id": _WF_ID,
    "name": "Loadtest",
    "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "s", "type": "set_data", "parameters": {"fields": {"n": "{{ $json.n }}"}}},
    ],
    "connections": [{"source": "t", "target": "s"}],
    "settings": {},
}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1)))))
    return ordered[k]


async def one_run(client: httpx.AsyncClient, headers: dict, results: list[dict[str, Any]]) -> None:
    t0 = time.perf_counter()
    resp = await client.post(f"/api/workflows/{_WF_ID}/run", json={"data": {"n": 1}}, headers=headers)
    if resp.status_code != 202:
        results.append({
            "ok": False, "phase": "run", "ms": (time.perf_counter() - t0) * 1000,
            "status": resp.status_code, "body": resp.text[:120],
        })
        return
    eid = resp.json()["data"]["execution_id"]
    while True:
        r = await client.get(f"/api/executions/{eid}", headers=headers)
        ms = (time.perf_counter() - t0) * 1000
        body = r.json()
        if r.status_code == 200 and "data" in body:
            st = body["data"]["status"]
            if st not in ("running", "queued", "cancelling"):
                results.append({"ok": st == "success", "phase": "terminal", "status": st, "ms": ms})
                return
        if ms > 30000:
            results.append({"ok": False, "phase": "timeout", "ms": ms})
            return
        await asyncio.sleep(0.05)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="loadtest@flowsmith.dev")
    parser.add_argument("--password", default="Loadtest123!")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    # Defaults calibrated for the dev topology: one embedded consumer
    # processes jobs serially (~2 runs/s), so end-to-end latency at
    # concurrency 10 is dominated by queue depth. Scale workers
    # (docker compose --scale worker=N) to raise throughput.
    parser.add_argument("--p95-ms", type=float, default=8000.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=30.0) as client:
        reg = await client.post("/api/auth/register", json={"email": args.email, "password": args.password})
        if reg.status_code == 201:
            token = reg.json()["data"]["token"]
        else:
            login = await client.post("/api/auth/login", json={"email": args.email, "password": args.password})
            if login.status_code != 200 or "data" not in login.json():
                print(f"FAIL: could not authenticate ({reg.status_code}/{login.status_code}): {login.text[:200]}")
                return 2
            token = login.json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        made = await client.post("/api/workflows", json=WORKFLOW, headers=headers)
        if made.status_code != 201:
            print(f"FAIL: could not create workflow ({made.status_code}) {made.text[:200]}")
            return 2

        results: list[dict[str, Any]] = []
        sem = asyncio.Semaphore(args.concurrency)

        async def worker() -> None:
            async with sem:
                await one_run(client, headers, results)

        t0 = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.iterations)))
        wall = time.perf_counter() - t0

    total = len(results)
    failures = [r for r in results if not r["ok"]]
    err_rate = len(failures) / total if total else 1.0
    lat = [r["ms"] for r in results]
    print(f"runs={total} errors={len(failures)} error_rate={err_rate:.3%} wall={wall:.1f}s "
          f"throughput={total / wall:.1f}/s")
    for p in (50, 90, 95, 99):
        print(f"  p{p}: {percentile(lat, p):.0f} ms")

    ok = True
    if err_rate > args.max_error_rate:
        print(f"FAIL: error rate {err_rate:.3%} > {args.max_error_rate:.1%}")
        ok = False
    p95 = percentile(lat, 95)
    if p95 > args.p95_ms:
        print(f"FAIL: p95 {p95:.0f}ms > {args.p95_ms:.0f}ms")
        ok = False
    if failures:
        from collections import Counter

        print("failure phases:", dict(Counter(str(f.get('phase')) for f in failures)))
        first = failures[0]
        if first.get("body"):
            print("first failure:", first.get("status"), first["body"])
    if ok:
        print("PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


