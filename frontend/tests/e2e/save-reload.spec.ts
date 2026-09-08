/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

test('save button persists the workflow across a browser refresh', async ({ page }) => {
  // 1. Register a new user via API
  const email = `save_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', {
    data: { email, password },
  });

  // 2. Login to get token
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { email, password },
  });
  const { data: { token } } = await loginRes.json();

  // 3. Go to app and set token in localStorage
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

  // 4. Reload to trigger auth, then navigate to workflow editor (new shell: root is overview)
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

  // 5. Edit the workflow: rename + add a node
  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    store.setName('Saved on Refresh');
    store.addNode('set_data', { x: 200, y: 100 });
  });

  // 6. Click the visible Save button
  await page.locator('button:has-text("Save")').click();

  // 7. The save-state indicator reports "saved"
  await expect(page.locator('.save-state')).toHaveText('saved', { timeout: 10000 });

  // 8. Refresh the browser: the workflow must reload from the server
  await page.reload();
  await page.waitForLoadState('networkidle');
  // After refresh we may be on overview; ensure we are on canvas
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const curId = await page.evaluate(() => window.__wfStore?.getState()?.workflow?.id || null);
    if (curId) {
      await page.goto(`http://localhost:5173/workflows/${curId}`);
      await page.waitForLoadState('networkidle');
      await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
    }
  }

  // 9. The name and the saved node survived the refresh
  await expect(page.locator('.workflow-name')).toHaveValue('Saved on Refresh');
  const nodes = await page.evaluate(() => window.__wfStore.getState().nodes);
  expect(nodes.map((n) => n.data?.node?.type).sort()).toEqual(['manual_trigger', 'set_data']);
  await expect(page.locator('.save-state')).toHaveText('saved', { timeout: 10000 });
});
