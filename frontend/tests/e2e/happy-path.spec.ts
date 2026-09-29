/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

test('happy path: register, load canvas, add nodes, connect, run, see green', async ({ page }) => {
  const email = `test_${Date.now()}@example.com`;
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
  await page.waitForLoadState('networkidle').catch(() => {});
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get('http://localhost:8000/api/workflows', { headers: { Authorization: `Bearer ${token}` } });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle').catch(() => {});
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }

  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    store.addNode('set_data', { x: 200, y: 100 });
    store.addNode('http_request', { x: 500, y: 100 });
  });
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    const httpNode = store.nodes.find((n) => n.data?.node?.type === 'http_request');
    if (httpNode) {
      store.updateNode(httpNode.id, { parameters: { url: 'http://127.0.0.1:8181/get', method: 'GET' } });
    }
  });

  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    const nodes = store.nodes;
    const trigger = nodes.find((n) => n.data?.node?.type === 'manual_trigger');
    const setNode = nodes.find((n) => n.data?.node?.type === 'set_data');
    if (trigger && setNode) {
      store.onConnect({
        source: trigger.id,
        target: setNode.id,
        sourceHandle: 'main',
        targetHandle: 'main',
      });
    }
  });
  await page.waitForTimeout(100);
  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    const nodes = store.nodes;
    const setNode = nodes.find((n) => n.data?.node?.type === 'set_data');
    const httpNode = nodes.find((n) => n.data?.node?.type === 'http_request');
    if (setNode && httpNode) {
      store.onConnect({
        source: setNode.id,
        target: httpNode.id,
        sourceHandle: 'main',
        targetHandle: 'main',
      });
    }
  });

  await page.waitForTimeout(2000);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.waitForFunction(() => {
    const store = window.__wfStore?.getState();
    return store && !store.saving;
  }, { timeout: 10000 });

  await page.locator('button.primary--run, button[aria-label="Run workflow"]').first().click();

  await expect(page.locator('.rf-node.status-success')).toHaveCount(2, { timeout: 30000 });
});
