/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

// Graph-based execution: fan-out, parallel branches, merge, and cycles.
// The engine runs nodes in topological order with parallel dispatch
// (asyncio ready-set scheduler). Cycles are allowed in the graph
// topology — each node still runs exactly once per execution pass.

test('fan-out to 3 parallel branches then merge', async ({ page }) => {
  const email = `graph_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', { data: { email, password } });
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', { data: { email, password } });
  const { data: { token } } = await loginRes.json();
  const api = page.request;
  const h = { Authorization: `Bearer ${token}` };

  // Create the workflow with a fan-out, parallel branches, and a merge node.
  // Structure: trigger -> {branch_a, branch_b, branch_c} -> merge
  const wfId = `wf_e2e_graph_${Date.now()}`;
  const createRes = await api.post('http://localhost:8000/api/workflows', {
    headers: h,
    data: {
      id: wfId,
      name: 'E2E Graph Fan-out',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', parameters: {}, position: { x: 0, y: 0 } },
        { id: 'branch_a', type: 'set_data', parameters: { fields: { branch: 'A' } }, position: { x: 300, y: 0 } },
        { id: 'branch_b', type: 'set_data', parameters: { fields: { branch: 'B' } }, position: { x: 300, y: 150 } },
        { id: 'branch_c', type: 'set_data', parameters: { fields: { branch: 'C' } }, position: { x: 300, y: 300 } },
        { id: 'merge', type: 'merge', parameters: { strategy: 'concat' }, position: { x: 600, y: 150 } },
      ],
      connections: [
        { source: 'trigger', target: 'branch_a' },
        { source: 'trigger', target: 'branch_b' },
        { source: 'trigger', target: 'branch_c' },
        { source: 'branch_a', target: 'merge' },
        { source: 'branch_b', target: 'merge' },
        { source: 'branch_c', target: 'merge' },
      ],
    },
  });
  expect(createRes.ok(), await createRes.text()).toBeTruthy();

  // Run the workflow
  const runRes = await api.post(`http://localhost:8000/api/workflows/${wfId}/run`, {
    headers: h,
    data: { data: {} },
  });
  expect(runRes.ok(), await runRes.text()).toBeTruthy();
  const { data: { execution_id } } = await runRes.json();

  // Wait for completion
  let exec;
  for (let i = 0; i < 60; i++) {
    const st = await api.get(`http://localhost:8000/api/executions/${execution_id}`, { headers: h });
    exec = (await st.json()).data;
    if (!['queued', 'running'].includes(exec.status)) break;
    await page.waitForTimeout(100);
  }
  expect(exec.status, JSON.stringify(exec.trace?.filter((s) => s.status === 'error'))).toBe('success');

  // All 5 nodes (trigger + 3 branches + merge) must have run successfully
  const steps = exec.trace || [];
  const successful = steps.filter((s) => s.status === 'success');
  expect(successful.map((s) => s.node_id).sort()).toEqual(['branch_a', 'branch_b', 'branch_c', 'merge', 'trigger']);

  // The merge node must have received items from all 3 branches
  const mergeStep = steps.find((s) => s.node_id === 'merge');
  const mergeInputs = mergeStep?.inputs || [];
  expect(mergeInputs.length).toBe(3);
  const branches = mergeInputs.map((i) => i.branch).sort();
  expect(branches).toEqual(['A', 'B', 'C']);
});

test('cycle in graph topology is tolerated and each node runs once', async ({ page }) => {
  const email = `cycle_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', { data: { email, password } });
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', { data: { email, password } });
  const { data: { token } } = await loginRes.json();
  const api = page.request;
  const h = { Authorization: `Bearer ${token}` };

  // Workflow with a 2-node cycle: trigger -> A -> B -> A (cycle) -> C
  // The cycle edge A->B->A means A appears twice in B's input edges
  // (once from trigger, once from B). A still runs exactly once.
  const wfId = `wf_e2e_cycle_${Date.now()}`;
  const createRes = await api.post('http://localhost:8000/api/workflows', {
    headers: h,
    data: {
      id: wfId,
      name: 'E2E Graph Cycle',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', parameters: {}, position: { x: 0, y: 0 } },
        { id: 'A', type: 'set_data', parameters: { fields: { stage: 'A' } }, position: { x: 300, y: 0 } },
        { id: 'B', type: 'set_data', parameters: { fields: { stage: 'B' } }, position: { x: 600, y: 0 } },
        { id: 'C', type: 'set_data', parameters: { fields: { stage: 'C' } }, position: { x: 900, y: 0 } },
      ],
      connections: [
        { source: 'trigger', target: 'A' },
        { source: 'A', target: 'B' },
        { source: 'B', target: 'A' },
        { source: 'B', target: 'C' },
      ],
    },
  });
  expect(createRes.ok(), await createRes.text()).toBeTruthy();

  // Run the workflow
  const runRes = await api.post(`http://localhost:8000/api/workflows/${wfId}/run`, {
    headers: h,
    data: { data: {} },
  });
  expect(runRes.ok(), await runRes.text()).toBeTruthy();
  const { data: { execution_id } } = await runRes.json();

  let exec;
  for (let i = 0; i < 60; i++) {
    const st = await api.get(`http://localhost:8000/api/executions/${execution_id}`, { headers: h });
    exec = (await st.json()).data;
    if (!['queued', 'running'].includes(exec.status)) break;
    await page.waitForTimeout(100);
  }
  expect(exec.status, JSON.stringify(exec.trace?.filter((s) => s.status === 'error'))).toBe('success');

  // All 4 nodes (trigger + A + B + C) must have run exactly once
  const steps = exec.trace || [];
  const nodeRuns = steps.reduce((acc, s) => {
    acc[s.node_id] = (acc[s.node_id] || 0) + 1;
    return acc;
  }, {});
  expect(nodeRuns['A']).toBe(1);
  expect(nodeRuns['B']).toBe(1);
  expect(nodeRuns['C']).toBe(1);
  expect(nodeRuns['trigger']).toBe(1);
});
