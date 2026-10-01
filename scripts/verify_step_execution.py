import requests
import time

API = "http://localhost:8000"

def main():
    email = f"test_step_{int(time.time())}@example.com"
    print(f"Registering user: {email}", flush=True)
    r = requests.post(f"{API}/api/auth/register", json={"email": email, "password": "P@ssword1"})
    print(f"Register response: {r.status_code}", flush=True)
    if r.status_code not in (200, 201):
        print("Register failed:", r.text, flush=True)
        return
    token = r.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("[1] Registered test user:", email, flush=True)

    # Create a 3-node workflow: Trigger -> Code 1 -> Code 2
    wf_id_val = f"wf_step_{int(time.time())}"
    wf = {
        "id": wf_id_val,
        "name": "Step Test Workflow",
        "nodes": [
            {"id": "trig_1", "type": "manual_trigger", "parameters": {}},
            {"id": "code_1", "type": "code", "parameters": {"code": "return [{ num: 42, msg: 'hello' }]", "language": "javascript"}},
            {"id": "code_2", "type": "code", "parameters": {"code": "return [{ doubled: $json.num * 2, received: $json.msg }]", "language": "javascript"}}
        ],
        "connections": [
            {"source": "trig_1", "target": "code_1"},
            {"source": "code_1", "target": "code_2"}
        ]
    }
    cr = requests.post(f"{API}/api/workflows", json=wf, headers=headers)
    assert cr.status_code in (200, 201), f"Create wf failed: {cr.text}"
    wf_id = cr.json()["data"]["id"]
    print("[2] Created test workflow:", wf_id, flush=True)

    # -------------------------------------------------------------
    # Test 1: Execute Step (run-node on trig_1)
    # -------------------------------------------------------------
    r_step1 = requests.post(f"{API}/api/workflows/{wf_id}/run-node", json={"node_id": "trig_1"}, headers=headers)
    assert r_step1.status_code == 202, f"Run-node trig_1 failed: {r_step1.text}"
    exec1_id = r_step1.json()["data"]["execution_id"]
    print("[3] Enqueued 'Execute Step' (trig_1):", exec1_id)

    for _ in range(20):
        time.sleep(0.5)
        e = requests.get(f"{API}/api/executions/{exec1_id}", headers=headers).json()["data"]
        if e["status"] in ("success", "failed"):
            print("    Status:", e["status"], "| Node statuses:", e.get("node_statuses"))
            assert e["status"] == "success", f"Execution failed: {e.get('error')}"
            assert e["node_statuses"].get("trig_1") == "success"
            break
    else:
        raise AssertionError("Execute Step 1 timed out")

    # -------------------------------------------------------------
    # Test 2: Previous Step (run-to-node on code_1)
    # -------------------------------------------------------------
    r_prev = requests.post(f"{API}/api/workflows/{wf_id}/run-to-node", json={"node_id": "code_1"}, headers=headers)
    assert r_prev.status_code == 202, f"Run-to-node code_1 failed: {r_prev.text}"
    exec2_id = r_prev.json()["data"]["execution_id"]
    print("[4] Enqueued 'Previous / Run to Node' (code_1):", exec2_id)

    for _ in range(20):
        time.sleep(0.5)
        e = requests.get(f"{API}/api/executions/{exec2_id}", headers=headers).json()["data"]
        if e["status"] in ("success", "failed"):
            print("    Status:", e["status"], "| Node statuses:", e.get("node_statuses"))
            assert e["status"] == "success", f"Execution failed: {e.get('error')}"
            assert e["node_statuses"].get("trig_1") == "success"
            assert e["node_statuses"].get("code_1") == "success"
            # Downstream node code_2 must NOT have run (seeded as skipped)
            assert e.get("node_statuses", {}).get("code_2") is None
            break
    else:
        raise AssertionError("Previous / Run-to-node timed out")

    # -------------------------------------------------------------
    # Test 3: Execute Step (run-node on code_2 using source_execution_id)
    # -------------------------------------------------------------
    r_step3 = requests.post(
        f"{API}/api/workflows/{wf_id}/run-node",
        json={"node_id": "code_2", "source_execution_id": exec2_id},
        headers=headers
    )
    assert r_step3.status_code == 202, f"Run-node code_2 failed: {r_step3.text}"
    exec3_id = r_step3.json()["data"]["execution_id"]
    print("[5] Enqueued 'Execute Step' (code_2 reusing code_1 data):", exec3_id)

    for _ in range(20):
        time.sleep(0.5)
        e = requests.get(f"{API}/api/executions/{exec3_id}", headers=headers).json()["data"]
        if e["status"] in ("success", "failed"):
            print("    Status:", e["status"], "| Node statuses:", e.get("node_statuses"))
            assert e["status"] == "success", f"Execution failed: {e.get('error')}"
            assert e["node_statuses"].get("code_2") == "success"
            outputs = (e.get("results") or {}).get("outputs", {})
            print("    code_2 outputs:", outputs.get("code_2"))
            main_out = outputs.get("code_2", {}).get("main", [])
            assert len(main_out) > 0
            assert main_out[0].get("doubled") == 84
            assert main_out[0].get("received") == "hello"
            break
    else:
        raise AssertionError("Execute Step 3 timed out")

    print("\n>>> ALL TESTS PASSED: Both 'Previous' and 'Execute Step' work flawlessly! <<<")

if __name__ == "__main__":
    main()
