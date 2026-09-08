/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

test('delete workflow: confirm dialog, disappears from list, survives refresh', async ({ page }) => {
  // 1. Register a new user via API
  const email = `del_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', {
    data: { email, password },
  });

  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { email, password },
  });
  const { data: { token } } = await loginRes.json();

  // 2. Go to app and set token in localStorage
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get('http://localhost:8000/api/workflows', { headers: { Authorization: `Bearer ${token}` } });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle');
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }

  // 3. Capture the freshly-created workflow
  const initial = await page.evaluate(() => {
    const s = window.__wfStore.getState();
    return { id: s.workflow.id, name: s.workflow.name };
  });
  expect(initial.name).toBe('My Workflow');

  // 4. Dismissing the confirmation keeps the workflow
  page.once('dialog', (d) => d.dismiss());
  await page.locator('button[aria-label="More actions"]').click();
  await page.locator('button:has-text("Delete workflow")').click();
  await page.waitForTimeout(300);
  const afterDismiss = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  expect(afterDismiss).toBe(initial.id);

  // 5. Confirming deletes it and switches to a fresh workflow
  page.once('dialog', (d) => d.accept());
  await page.locator('button[aria-label="More actions"]').click();
  await page.locator('button:has-text("Delete workflow")').click();
  await page.waitForFunction(
    (oldId) => {
      const wf = window.__wfStore.getState().workflow;
      return wf !== null && wf.id !== oldId;
    },
    initial.id,
    { timeout: 10000 },
  );

  const now = await page.evaluate(() => {
    const s = window.__wfStore.getState();
    return { id: s.workflow.id, name: s.workflow.name };
  });
  expect(now.id).not.toBe(initial.id);
  expect(now.name).toBe('My Workflow'); // empty account -> a fresh workflow

  // The deleted workflow is gone from the backend.
  const deleted = await page.request.get(`http://localhost:8000/api/workflows/${initial.id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(deleted.status()).toBe(404);
  const list = await page.request.get('http://localhost:8000/api/workflows', {
    headers: { Authorization: `Bearer ${token}` },
  });
  const ids = (await list.json()).data.map((w) => w.id);
  expect(ids).not.toContain(initial.id);

  // 6. Refresh: the app boots on the fresh workflow, never the deleted one
  await page.reload();
  await page.waitForLoadState('networkidle');
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get('http://localhost:8000/api/workflows', { headers: { Authorization: `Bearer ${token}` } });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle');
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }
  await expect(page.locator('.workflow-name')).toHaveValue('My Workflow');
  const afterRefresh = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  expect(afterRefresh).toBe(now.id);
});