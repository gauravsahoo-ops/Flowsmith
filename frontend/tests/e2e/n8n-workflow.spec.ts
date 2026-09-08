/// <reference path="./global.d.ts" />
/**
 * E2E test: n8n-style workflow (Schedule Trigger → Code → Login → IF →
 * Get Data → Split → Loop → Code → Search → IF → Create/Update).
 *
 * Proves that the platform can execute a real-world n8n workflow with:
 * - HTTP Request nodes (login, GET data, search, POST create, PATCH update)
 * - Code nodes (JS transformation)
 * - IF condition branching
 * - Split + Loop Over Items
 * - Create/Update branching based on search result
 */
import { test, expect } from '@playwright/test';

const API = 'http://localhost:8000';
const STUB = 'http://127.0.0.1:8182';

function auth(token: string) {
  return { Authorization: `Bearer ${token}` };
}

async function registerAndLogin(page) {
  const email = `n8n_${Date.now()}@example.com`;
  await page.request.post(`${API}/api/auth/register`, { data: { email, password: 'P@ssword1' } });
  const lr = await page.request.post(`${API}/api/auth/login`, { data: { email, password: 'P@ssword1' } });
  const { data } = await lr.json();
  return { email, token: data.token };
}

async function gotoApp(page, token) {
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get(`${API}/api/workflows`, { headers: auth(token) });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle');
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }
}

async function addNode(page, type, x, y) {
  return page.evaluate(
    ({ type, x, y }) => {
      window.__wfStore.getState().addNode(type, { x, y });
      const all = window.__wfStore.getState().nodes.filter((n) => n.data?.node?.type === type);
      return all[all.length - 1].data.node.id;
    },
    { type, x, y },
  );
}

async function setParams(page, nodeId, params) {
  await page.evaluate(
    ({ nodeId, params }) => {
      const store = window.__wfStore.getState();
      const n = store.nodes.find((n) => n.data?.node?.id === nodeId);
      store.updateNode(n.id, { parameters: params });
    },
    { nodeId, params },
  );
}

async function connect(page, sourceId, targetId, sourceHandle = 'main', targetHandle = 'main') {
  await page.evaluate(
    ({ sourceId, targetId, sourceHandle, targetHandle }) => {
      window.__wfStore.getState().onConnect({ source: sourceId, target: targetId, sourceHandle, targetHandle });
    },
    { sourceId, targetId, sourceHandle, targetHandle },
  );
}

async function saveWorkflow(page) {
  await page.waitForTimeout(2000);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.waitForFunction(
    () => {
      const s = window.__wfStore?.getState();
      return s && !s.saving;
    },
    { timeout: 10000 },
  );
}

async function latestExecutionId(page, token, workflowId) {
  const res = await page.request.get(`${API}/api/executions?workflow_id=${workflowId}&pageSize=20`, { headers: auth(token) });
  const list = (await res.json()).data;
  const found = list.find((e) => e.workflow_id === workflowId && e.status === 'success');
  expect(found, 'a successful execution exists').toBeTruthy();
  return found.id;
}

async function trace(page, token, executionId) {
  const res = await page.request.get(`${API}/api/executions/${executionId}/trace`, { headers: auth(token) });
  return (await res.json()).data.steps;
}

test('n8n workflow: trigger → code → login → IF → get data → split → loop → code → search → IF → create/update', async ({ page }) => {
  const { token } = await registerAndLogin(page);
  await gotoApp(page, token);

  // ── Build the workflow graph ────────────────────────────────
  // 1. Manual Trigger
  // 2. Code (JS) — prepare login payload
  // 3. HTTP Request — Login Api (POST)
  // 4. IF — check login success
  // 5. HTTP Request — Get Extracted Data (GET)
  // 6. Split — split items
  // 7. Loop Over Items — loop
  // 8. Code (JS) — run for each item
  // 9. HTTP Request — search custom object (GET)
  // 10. IF — check if exists
  // 11. HTTP Request — Create (POST) [true branch]
  // 12. HTTP Request — Update (PATCH) [false branch]

  const triggerId = await addNode(page, 'manual_trigger', 0, 200);
  const code1Id = await addNode(page, 'code', 200, 200);
  const loginId = await addNode(page, 'http_request', 400, 200);
  const if1Id = await addNode(page, 'if_condition', 600, 200);
  const getDataId = await addNode(page, 'http_request', 800, 100);
  const splitId = await addNode(page, 'split', 1000, 100);
  const loopId = await addNode(page, 'loop_over_items', 1200, 100);
  const code2Id = await addNode(page, 'code', 1400, 100);
  const searchId = await addNode(page, 'http_request', 1600, 100);
  const if2Id = await addNode(page, 'if_condition', 1800, 100);
  const createId = await addNode(page, 'http_request', 2000, 0);
  const updateId = await addNode(page, 'http_request', 2000, 200);

  // ── Configure nodes ─────────────────────────────────────────

  // Code 1: prepare login payload
  await setParams(page, code1Id, {
    language: 'javascript',
    code: `return [{ json: { email: 'admin@test.com', password: 'secret123' } }];`,
  });

  // Login Api: POST to stub
  await setParams(page, loginId, {
    method: 'POST',
    url: `${STUB}/api/login`,
    sendHeaders: true,
    headers: { 'Content-Type': 'application/json' },
    sendBody: true,
    bodyContentType: 'json',
    body: { email: 'admin@test.com', password: 'secret123' },
  });

  // IF 1: check if login returned a token
  await setParams(page, if1Id, {
    condition: { left: '$json.body.token', operator: 'is not empty', right: '' },
  });

  // Get Extracted Data: GET items from stub
  await setParams(page, getDataId, {
    method: 'GET',
    url: `${STUB}/api/data`,
  });

  // Split: split the items array
  await setParams(page, splitId, {});

  // Loop Over Items: iterate
  await setParams(page, loopId, {});

  // Code 2: per-item transformation (just pass through)
  await setParams(page, code2Id, {
    language: 'javascript',
    code: `return items;`,
  });

  // Search custom object: GET search by email
  await setParams(page, searchId, {
    method: 'GET',
    url: `${STUB}/api/search/test@test.com`,
  });

  // IF 2: check if record exists
  await setParams(page, if2Id, {
    condition: { left: '$json.body.found', operator: 'is equal to', right: true },
  });

  // Create: POST new object
  await setParams(page, createId, {
    method: 'POST',
    url: `${STUB}/api/objects`,
    sendBody: true,
    bodyContentType: 'json',
    body: { source: 'workflow', action: 'create' },
  });

  // Update: PATCH existing object
  await setParams(page, updateId, {
    method: 'PATCH',
    url: `${STUB}/api/objects/rec_001`,
    sendBody: true,
    bodyContentType: 'json',
    body: { source: 'workflow', action: 'update' },
  });

  // ── Wire connections ────────────────────────────────────────
  await connect(page, triggerId, code1Id);
  await connect(page, code1Id, loginId);
  await connect(page, loginId, if1Id);
  // IF true → Get Data
  await connect(page, if1Id, getDataId, 'true', 'main');
  await connect(page, getDataId, splitId);
  await connect(page, splitId, loopId);
  await connect(page, loopId, code2Id);
  await connect(page, code2Id, searchId);
  await connect(page, searchId, if2Id);
  // IF2 true → Create, IF2 false → Update
  await connect(page, if2Id, createId, 'true', 'main');
  await connect(page, if2Id, updateId, 'false', 'main');

  // ── Save and run ────────────────────────────────────────────
  await saveWorkflow(page);
  await page.locator('button:has-text("▶ Run")').click();

  // Wait for execution to complete — the topbar shows "success"
  await expect(page.locator('.topbar .run-status.status-success')).toHaveText('success', { timeout: 60000 });

  // ── Verify trace ────────────────────────────────────────────
  const wfId = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  const executionId = await latestExecutionId(page, token, wfId);
  const steps = await trace(page, token, executionId);

  // All 12 nodes should have executed (no skips for this topology)
  const executedTypes = steps.filter((s) => s.status === 'success').map((s) => s.node_type);
  expect(executedTypes).toContain('manual_trigger');
  expect(executedTypes).toContain('code');
  expect(executedTypes).toContain('http_request');
  expect(executedTypes).toContain('if_condition');
  expect(executedTypes).toContain('split');
  expect(executedTypes).toContain('loop_over_items');

  // The search node should have returned found: false (new emails)
  const searchStep = steps.find((s) => s.node_type === 'http_request' && s.outputs?.main?.[0]?.body?.found !== undefined);
  expect(searchStep).toBeTruthy();
  expect(searchStep.outputs.main[0].body.found).toBe(false);

  // The IF2 should have routed to the create (false branch = not found)
  const createStep = steps.find((s) => s.node_type === 'http_request' && s.outputs?.main?.[0]?.body?.success === true && s.outputs?.main?.[0]?.body?.id?.startsWith('rec_'));
  expect(createStep).toBeTruthy();
});
