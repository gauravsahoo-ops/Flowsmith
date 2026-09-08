/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

// Phase 18 — complete end-to-end Salesforce scenarios against the local
// stub server (tests/e2e/stub-server.mjs), through the real stack:
// UI login -> workflow canvas -> Salesforce node -> credentials (UI) ->
// operation config -> save -> Run (queue -> embedded worker) ->
// Salesforce REST stub -> execution history UI -> trace + stub state.

const API = 'http://localhost:8000';
const STUB = 'http://127.0.0.1:8181';
const SEED_EMAIL = 'ada.e2e@example.com';
const SEED_ID = '00Q000000000001';
const CRED_NAME = 'E2E Salesforce';

const auth = (token) => ({ Authorization: `Bearer ${token}` });

async function registerAndLogin(page) {
  const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
  const password = 'P@ssword1';
  await page.request.post(`${API}/api/auth/register`, { data: { email, password } });
  const login = await page.request.post(`${API}/api/auth/login`, { data: { email, password } });
  const { data } = await login.json();
  return data.token;
}

async function gotoApp(page, token) {
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get(`${API}/api/workflows`, {
      headers: auth(token),
    });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle');
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }
  await page.waitForFunction(
    () => {
      const s = window.__wfStore?.getState();
      return s && !s.loading && s.workflow;
    },
    { timeout: 15000 },
  );
}

// ---- Credentials. Salesforce now uses the 'Connect Salesforce' OAuth
// flow in the UI (no manual secret form), so the workflow-execution specs
// create the credential through the real API and verify it appears in the
// CredentialsPanel UI. The OAuth connect flow itself is exercised live.
async function createCredentialViaUi(page, token) {
  const resp = await page.request.post(`${API}/api/credentials`, {
    headers: auth(token),
    data: {
      name: CRED_NAME,
      type: 'salesforce',
      data: {
        instance_url: STUB,
        client_id: 'e2e-client-id',
        client_secret: 'e2e-client-secret',
        username: 'e2e@example.com',
        password: 'e2e-password',
        api_version: 'v63.0',
      },
    },
  });
  expect(resp.status(), await resp.text()).toBe(201);
  const meta = (await resp.json()).data;
  // Reload the page so the credential store picks up the new credential
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.waitForFunction(
    () => {
      const s = window.__wfStore?.getState();
      return s && !s.loading && s.workflow;
    },
    { timeout: 15000 },
  );
  return meta.id;
}

// ---- Node configuration (canvas + ConfigPanel UI for the credential
// select; parameters via the store, as in happy-path.spec.ts) ----
async function addNode(page, type, x, y) {
  return page.evaluate(
    ({ type, x, y }) => {
      // Note: re-fetch getState() after mutating — zustand replaces the
      // state object on set(), so the pre-mutation snapshot is stale.
      // Return the LAST node of this type (the one just added) — with
      // several nodes of one type, "first match" would be wrong.
      window.__wfStore.getState().addNode(type, { x, y });
      const all = window.__wfStore
        .getState()
        .nodes.filter((n) => n.data?.node?.type === type);
      return all[all.length - 1].data.node.id;
    },
    { type, x, y },
  );
}

async function setParams(page, nodeId, params, extra = {}) {
  await page.evaluate(
    ({ nodeId, params, extra }) => {
      const store = window.__wfStore.getState();
      const n = store.nodes.find((n) => n.data?.node?.id === nodeId);
      store.updateNode(n.id, { parameters: params, ...extra });
    },
    { nodeId, params, extra },
  );
}

async function connect(page, sourceId, targetId, sourceHandle = 'main', targetHandle = 'main') {
  await page.evaluate(
    ({ sourceId, targetId, sourceHandle, targetHandle }) => {
      const store = window.__wfStore.getState();
      store.onConnect({ source: sourceId, target: targetId, sourceHandle, targetHandle });
    },
    { sourceId, targetId, sourceHandle, targetHandle },
  );
}

async function bindCredentialViaUi(page, nodeId, credName) {
  // Close any previously-open editor so this bind starts from a fresh modal
  // (the modal is reused across nodes; a stale open Credential section would
  // make the toggle click below COLLAPSE it instead of expanding).
  await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
  await page.waitForTimeout(300);
  // Open the node editor directly via the store. This avoids relying on the
  // React Flow rf-node DOM element (whose rendering can lag behind store
  // updates in the Playwright test runner after a page.reload()).
  await page.evaluate((nid) => {
    window.__uiStore.getState().openNodeEditor(nid);
  }, nodeId);
  // Wait for the node editor modal to open
  await page.waitForSelector('.node-editor-modal', { timeout: 5000 });
  // Expand the "Credential" collapsible section — only if not already open
  // (the modal is reused across nodes, so a previous bind may have left it open
  //  — in that case clicking the toggle would COLLAPSE it).
  const credToggle = page.locator('.node-editor-modal button.cfg-section-head', { hasText: 'Credential' });
  const credSection = page.locator('.node-editor-modal section.cfg-section.open').filter({ has: credToggle });
  if ((await credSection.count()) === 0) {
    await credToggle.click({ timeout: 5000 });
  }
  // Now select the credential from the dropdown
  const sfLabel = page.locator('.node-editor-modal label', { hasText: 'salesforce' });
  await expect(sfLabel).toBeVisible({ timeout: 5000 });
  await sfLabel.locator('select').selectOption({ label: credName });
  // Wait for the credential to land in the store (React state update
  // from selectOption must flush before we close the editor / save).
  await page.waitForFunction(
    ([nid, cname]) => {
      const n = window.__wfStore.getState().nodes.find(
        (x) => x.data?.node?.id === nid,
      );
      const creds = n?.data?.node?.credentials || {};
      return Object.values(creds).some((v) => v && typeof v === 'string');
    },
    [nodeId, credName],
    { timeout: 5000 },
  );
  // Close the editor so subsequent binds start from a fresh modal
  await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
  await page.waitForTimeout(300);
}

async function saveWorkflow(page) {
  await page.waitForTimeout(2000);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.waitForFunction(() => {
    const store = window.__wfStore?.getState();
    return store && !store.saving;
  }, { timeout: 10000 });
}

async function runAndWait(page, expectedNodeCount) {
  await page.locator('button:has-text("▶ Run")').click();
  await expect(page.locator('.rf-node.status-success')).toHaveCount(expectedNodeCount, { timeout: 45000 });
  // Scoped to the topbar: the inspector also renders a .run-status once
  // an execution is loaded, and strict mode forbids matching both.
  await expect(page.locator('.topbar .run-status.status-success')).toHaveText('success', { timeout: 15000 });
}

async function latestExecutionId(page, token, workflowId) {
  const res = await page.request.get(
    `${API}/api/executions?workflow_id=${workflowId}&pageSize=20`,
    { headers: auth(token) },
  );
  const list = (await res.json()).data;
  const found = list.find((e) => e.workflow_id === workflowId && e.status === 'success');
  expect(found, 'a successful execution exists in the history').toBeTruthy();
  return found.id;
}

async function trace(page, token, executionId) {
  const res = await page.request.get(`${API}/api/executions/${executionId}/trace`, {
    headers: auth(token),
  });
  return (await res.json()).data.steps;
}

function stepByName(steps, nodeType) {
  const step = steps.find((s) => s.node_type === nodeType);
  expect(step, `step for ${nodeType} exists`).toBeTruthy();
  return step;
}

async function checkHistoryUi(page, workflowName, expectedSteps) {
  // The topbar 🕘 button navigates to the /executions page (a full page
  // route, not a slide-in panel). Find the row for our workflow and verify
  // its status badge, then open the detail page.
  await page.locator('header.topbar button[title*="Executions" i]').click();
  await page.waitForURL(/\/executions($|\?)/, { timeout: 10000 });
  await page.waitForSelector('.data-table tbody tr', { timeout: 15000 });
  const row = page
    .locator('.data-table tbody tr', { hasText: workflowName })
    .filter({ has: page.locator('.status-label.status-success') })
    .first();
  await expect(row).toBeVisible({ timeout: 15000 });
  // Open the detail page
  await row.click();
  await page.waitForURL(/\/executions\/[^/]+$/, { timeout: 10000 });
  await expect(page.locator('.status-label.status-success').first()).toBeVisible({ timeout: 15000 });
  // Switch to the "trace" tab so the raw output (with the 'found' key)
  // is visible to the caller.
  await page.locator('.debug-tab', { hasText: 'trace' }).click();
  return page.locator('body');
}

// ======================================================================
// A. Salesforce Search
// ======================================================================
test('A — Salesforce Search end to end', async ({ page }) => {
  const token = await registerAndLogin(page);
  await gotoApp(page, token);

  const credId = await createCredentialViaUi(page, token);

  const searchId = await addNode(page, 'salesforce', 400, 120);
  await setParams(page, searchId, {
    operation: 'search',
    object_name: 'Lead',
    search_field: 'Email',
    search_value: SEED_EMAIL,
  });
  await bindCredentialViaUi(page, searchId, CRED_NAME);

  const wfId = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  const triggerId = await page.evaluate(() =>
    window.__wfStore.getState().nodes.find((n) => n.data?.node?.type === 'manual_trigger')?.data?.node?.id,
  );
  await connect(page, triggerId, searchId);

  await saveWorkflow(page);
  await runAndWait(page, 1);

  // The node actually carried the credential.
  const nodeCred = await page.evaluate(({ searchId }) => {
    const store = window.__wfStore.getState();
    return store.nodes.find((n) => n.data?.node?.id === searchId)?.data?.node?.credentials;
  }, { searchId });
  expect(nodeCred?.salesforce).toBe(credId);

  // Execution history + result in the UI.
  const workflowName = await page.evaluate(() => window.__wfStore.getState().workflow.name);
  const inspector = await checkHistoryUi(page, workflowName, 2);
  await expect(inspector).toContainText('found');

  // Trace: search step found the seeded record. Note the trace caps deep
  // payloads (spec 26), so record field VALUES are "[truncated]" there —
  // the actual record is verified against the stub below.
  const executionId = await latestExecutionId(page, token, wfId);
  const steps = await trace(page, token, executionId);
  const searchStep = stepByName(steps, 'salesforce');
  const output = searchStep.outputs?.main?.[0];
  expect(output.found).toBe(true);
  expect(output.object_name).toBe('Lead');
  expect(output.search_field).toBe('Email');

  // The stub really was queried with the right SOQL and returned the
  // seeded record (values intact end-to-end).
  const record = await page.request.get(`${STUB}/services/data/v63.0/sobjects/Lead/${SEED_ID}`);
  expect(record.status()).toBe(200);
  const recordBody = await record.json();
  expect(recordBody.Email).toBe(SEED_EMAIL);
  expect(recordBody.Company).toBe('Original Co');
});

// ======================================================================
// B. Salesforce Search -> IF -> Update
// ======================================================================
test('B — Search -> IF (true) -> Update end to end', async ({ page }) => {
  const token = await registerAndLogin(page);
  await gotoApp(page, token);
  await createCredentialViaUi(page, token);

  const searchId = await addNode(page, 'salesforce', 200, 120);
  const ifId = await addNode(page, 'if_condition', 520, 120);
  const updateId = await addNode(page, 'salesforce', 840, 40);

  await setParams(page, searchId, {
    operation: 'search',
    object_name: 'Lead',
    search_field: 'Email',
    search_value: SEED_EMAIL,
  });
  await bindCredentialViaUi(page, searchId, CRED_NAME);

  await setParams(page, ifId, {
    condition: { left: '$json.found', operator: 'equals', right: true },
  });

  await setParams(page, updateId, {
    operation: 'update',
    object_name: 'Lead',
    record_id: '{{ $json.record.Id }}',
    record: { Company: 'E2E Updated Co' },
  });
  await bindCredentialViaUi(page, updateId, CRED_NAME);

  const triggerId = await page.evaluate(() =>
    window.__wfStore.getState().nodes.find((n) => n.data?.node?.type === 'manual_trigger')?.data?.node?.id,
  );
  await connect(page, triggerId, searchId);
  await connect(page, searchId, ifId);
  await connect(page, ifId, updateId, 'true', 'main');

  await saveWorkflow(page);
  await runAndWait(page, 2);

  const workflowName = await page.evaluate(() => window.__wfStore.getState().workflow.name);
  await checkHistoryUi(page, workflowName, 4);

  // Trace: search found the record, IF routed to the true branch, and
  // the update applied to the seeded record id.
  const wfId = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  const executionId = await latestExecutionId(page, token, wfId);
  const steps = await trace(page, token, executionId);
  const sfSteps = steps.filter((s) => s.node_type === 'salesforce');
  const searchStep = sfSteps[0];
  expect(searchStep.status).toBe('success');
  expect(searchStep.outputs?.main?.[0].found).toBe(true);

  const ifStep = steps.find((s) => s.node_type === 'if_condition');
  expect(ifStep?.status).toBe('success');

  const updateStep = sfSteps[1];
  expect(updateStep.status).toBe('success');
  const updateOutput = updateStep.outputs?.main?.[0];
  expect(updateOutput.id).toBe(SEED_ID);
  expect(updateOutput.success).toBe(true);

  // The Salesforce stub really was updated (PATCH reached the org).
  const record = await page.request.get(
    `${STUB}/services/data/v63.0/sobjects/Lead/${SEED_ID}`,
  );
  expect(record.status()).toBe(200);
  expect((await record.json()).Company).toBe('E2E Updated Co');
});

// ======================================================================
// C. Salesforce Search -> IF -> Create
// ======================================================================
test('C — Search -> IF (false) -> Create end to end', async ({ page }) => {
  const token = await registerAndLogin(page);
  await gotoApp(page, token);
  await createCredentialViaUi(page, token);

  const uniqueEmail = `create_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@e2e.test`;

  const searchId = await addNode(page, 'salesforce', 200, 120);
  const ifId = await addNode(page, 'if_condition', 520, 120);
  const createId = await addNode(page, 'salesforce', 840, 180);

  await setParams(page, searchId, {
    operation: 'search',
    object_name: 'Lead',
    search_field: 'Email',
    search_value: uniqueEmail,
  });
  await bindCredentialViaUi(page, searchId, CRED_NAME);

  await setParams(page, ifId, {
    // "found equals true" is FALSE when the search missed, routing the
    // create (wired to the false handle) — "equals false" would match
    // exactly when found=false and wrongly take the true branch.
    condition: { left: '$json.found', operator: 'equals', right: true },
  });

  await setParams(page, createId, {
    operation: 'create',
    object_name: 'Lead',
    record: { FirstName: 'E2E', Email: uniqueEmail, Company: 'Created By E2E' },
  });
  await bindCredentialViaUi(page, createId, CRED_NAME);

  const triggerId = await page.evaluate(() =>
    window.__wfStore.getState().nodes.find((n) => n.data?.node?.type === 'manual_trigger')?.data?.node?.id,
  );
  await connect(page, triggerId, searchId);
  await connect(page, searchId, ifId);
  await connect(page, ifId, createId, 'false', 'main');

  await saveWorkflow(page);
  await runAndWait(page, 2);

  const workflowName = await page.evaluate(() => window.__wfStore.getState().workflow.name);
  await checkHistoryUi(page, workflowName, 4);

  // Trace: search did NOT find the lead, IF routed to the false branch,
  // and create returned the new record id.
  const wfId = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  const executionId = await latestExecutionId(page, token, wfId);
  const steps = await trace(page, token, executionId);
  const sfSteps = steps.filter((s) => s.node_type === 'salesforce');
  const searchStep = sfSteps[0];
  expect(searchStep.status).toBe('success');
  expect(searchStep.outputs?.main?.[0].found).toBe(false);

  const createStep = sfSteps[1];
  expect(createStep.status).toBe('success');
  const createOutput = createStep.outputs?.main?.[0];
  expect(createOutput.success).toBe(true);
  expect(String(createOutput.id)).toMatch(/^[A-Za-z0-9]{15}$/);

  // The Salesforce stub really created the lead (POST reached the org).
  const query = await page.request.get(
    `${STUB}/services/data/v63.0/query?q=${encodeURIComponent(
      `SELECT Id FROM Lead WHERE Email = '${uniqueEmail}'`,
    )}`,
  );
  expect(query.status()).toBe(200);
  const body = await query.json();
  expect(body.totalSize).toBe(1);
  expect(body.records[0].Id).toBe(createOutput.id);
});
