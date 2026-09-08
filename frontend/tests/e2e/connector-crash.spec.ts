/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

const CONNECTORS = ['gmail', 'google_sheets', 'google_calendar', 'hubspot', 'salesforce'];

async function setupUser(page: import('@playwright/test').Page) {
  const email = `conn_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@example.com`;
  const password = 'P@ssword1';

  await page.request.post('http://localhost:8000/api/auth/register', {
    data: { email, password },
  });
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { email, password },
  });
  const { data: { token } } = await loginRes.json();

  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
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

test('connector nodes: add + click + run do not crash', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`);
  });

  await setupUser(page);

  const nodeIds: string[] = [];
  for (const type of CONNECTORS) {
    const nodeId = await page.evaluate((t) => {
      const store = window.__wfStore.getState();
      const trigger = store.nodes.find((n) => n.data?.node?.type === 'manual_trigger');
      const baseX = trigger?.position?.x ?? 0;
      const baseY = trigger?.position?.y ?? 0;
      const id = store.addNode(t, { x: baseX + 250, y: baseY + 50 });
      return id;
    }, type);

    expect(nodeId, `${type} node was added to store`).toBeTruthy();
    nodeIds.push(nodeId!);

    await page.waitForTimeout(500);

    const domCount = await page.evaluate(() => document.querySelectorAll('.rf-node').length);
    console.log(`[${type}] storeNodeId=${nodeId} domNodes=${domCount}`);

    await page.locator('.rf-node').last().click();
    await page.waitForTimeout(500);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
    await page.waitForTimeout(200);
  }

  await page.waitForTimeout(500);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.locator('button:has-text("▶ Run")').click();
  await page.waitForTimeout(8000);

  await expect(page.locator('.canvas')).toBeAttached();
  expect(errors, `JS errors:\n${errors.join('\n')}`).toEqual([]);
});
