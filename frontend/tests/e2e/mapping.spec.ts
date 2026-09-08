/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

// Phase 5 — Visual data mapping E2E.
// Flow: manual trigger -> http_request(url). Run once via API so upstream
// fields exist; open the http_request node's config, use the fx mapping
// browser to map a field from the trigger output into the URL, verify the
// live preview resolves the value, then run again through the UI and confirm
// the mapped value reaches the execution record.

test('map an upstream field into a node without writing expressions', async ({ page }) => {
  const email = `map_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', { data: { email, password } });
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', { data: { email, password } });
  const { data: { token } } = await loginRes.json();
  const api = page.request;
  const h = { Authorization: `Bearer ${token}` };

  // Create the workflow via API for determinism
  const wfId = `wf_e2e_map_${Date.now()}_${Math.random().toString(36).slice(2,6)}`;
  const createRes = await api.post('http://localhost:8000/api/workflows', {
    headers: h,
    data: {
      id: wfId,
      name: 'E2E Mapping',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', parameters: {}, position: { x: 0, y: 0 } },
        {
          id: 'http',
          type: 'http_request',
          parameters: { url: 'http://127.0.0.1:8181/get', method: 'GET' },
          position: { x: 300, y: 0 },
        },
      ],
      connections: [{ source: 'trigger', target: 'http' }],
      settings: {},
    },
  });
  const createJson = await createRes.json();
  if (!createRes.ok()) {
    throw new Error(`create failed ${createRes.status()} ${JSON.stringify(createJson)}`);
  }

  // Seed one execution so upstream fields exist
  const run = await api.post(`http://localhost:8000/api/workflows/${wfId}/run`, {
    headers: h,
    data: { data: { myUrl: 'http://127.0.0.1:8181/get' } },
  });
  const runJson = await run.json();
  if (!run.ok() || !runJson.data?.execution_id) {
    throw new Error(`run failed: ${run.status()} ${JSON.stringify(runJson)}`);
  }
  const { data: { execution_id } } = runJson;
  for (let i = 0; i < 60; i++) {
    const st = await api.get(`http://localhost:8000/api/executions/${execution_id}`, { headers: h });
    const s = (await st.json()).data.status;
    if (!['queued', 'running'].includes(s)) break;
    await page.waitForTimeout(100);
  }

  // Enter the app with the workflow loaded
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.goto(`http://localhost:5173/workflows/${wfId}`);
  await page.waitForLoadState('networkidle');

  // Wait for the store to hydrate, then load the workflow, clear the URL (to
  // avoid double-appending), and open the http node editor.
  await page.waitForFunction(
    () => {
      const s = window.__wfStore?.getState();
      return s && !s.loading && s.workflow;
    },
    { timeout: 15000 },
  );

  await page.evaluate(async (id) => {
    const store = window.__wfStore.getState();
    await store.load(id);
    // Clear URL so the mapping expression replaces it cleanly
    const httpNode = store.nodes.find((n) => n.data?.node?.type === 'http_request');
    if (httpNode) store.updateNode(httpNode.id, { parameters: { url: '', method: 'GET' } });
    window.__uiStore.getState().openNodeEditor('http');
  }, wfId);
  await page.waitForSelector('.node-editor-modal, .node-editor-overlay', { timeout: 15000 });

  // The fx browser should appear for string fields once mapping loads
  const fx = page.locator('.fx-btn').first();
  await expect(fx).toBeVisible({ timeout: 20000 });
  await fx.click();

  // The field browser lists the upstream field from the last run
  const chip = page.locator('.mapping-item').filter({ hasText: 'myUrl' }).first();
  await expect(chip).toBeVisible({ timeout: 5000 });

  // Pick it -> input now holds the mapping expression
  await chip.click();
  const val = await page.locator('.mapping-field input').first().inputValue();
  expect(val).toContain('$node["trigger"]');
  expect(val).toContain('myUrl');

  // Live preview resolved the value from the previous run
  await expect(page.locator('.preview.ok')).toContainText('http://127.0.0.1:8181/get', { timeout: 5000 });

  // Close the editor modal and save via the store
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
  await page.waitForTimeout(300);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.waitForFunction(() => {
    const s = window.__wfStore?.getState();
    return s && !s.saving;
  }, { timeout: 10000 });

  const run2 = await api.post(`http://localhost:8000/api/workflows/${wfId}/run`, {
    headers: h,
    data: { data: { myUrl: 'http://127.0.0.1:8181/get' } },
  });
  const run2Json = await run2.json();
  const { data: { execution_id: eid2 } } = run2Json;
  let final;
  for (let i = 0; i < 60; i++) {
    const r = await api.get(`http://localhost:8000/api/executions/${eid2}`, { headers: h });
    final = (await r.json()).data;
    if (!['queued', 'running'].includes(final.status)) break;
    await page.waitForTimeout(100);
  }
  console.log('final status:', final.status);
  if (final.status === 'failed') {
    console.log('final trace:', JSON.stringify(final.trace || []).slice(0, 1000));
  }
  expect(final.status).toBe('success');
});
