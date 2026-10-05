/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { execSync } from 'node:child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const catalogData = JSON.parse(readFileSync(join(__dirname, '../../src/all_catalog_items.json'), 'utf-8'));

async function setupTestUser(page: import('@playwright/test').Page) {
  const token = execSync('python tests/e2e/get_token.py', {
    cwd: join(__dirname, '../..'),
    encoding: 'utf-8',
  })
    .trim()
    .split(/\r?\n/)
    .pop()!;

  const wfRes = await page.request.post('http://localhost:8000/api/workflows', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `Audit Workflow ${Date.now()}` },
  });
  const wfJson = await wfRes.json();
  const wfId = wfJson.data?.id;

  await page.addInitScript((t) => {
    localStorage.setItem('mat_token', t);
  }, token);

  await page.goto(`http://localhost:5173/workflows/${wfId}`);
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });

  await page.waitForFunction(
    () => {
      const s = window.__wfStore?.getState();
      return s && !s.loading && s.workflow;
    },
    { timeout: 15000 },
  );

  return token;
}

test.describe('Exhaustive Connectors & Nodes Audit', () => {
  test.setTimeout(240000);

  test('1. Builtin Flow Nodes Audit: all 66 built-in node types add, render on canvas, and open editor without error', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (text.includes('Failed to load resource')) return;
        errors.push(`console.error: ${text}`);
      }
    });

    await setupTestUser(page);

    const builtins: string[] = catalogData.builtins || [];
    expect(builtins.length).toBeGreaterThanOrEqual(60);

    let count = 0;
    for (const type of builtins) {
      const nodeId = await page.evaluate(
        ({ type: t, count: c }) => {
          const store = window.__wfStore.getState();
          const trigger = store.nodes.find((n: any) => n.data?.node?.type === 'manual_trigger');
          const baseX = trigger?.position?.x ?? 0;
          const baseY = trigger?.position?.y ?? 0;
          return store.addNode(t, { x: baseX + 180 + (c % 8) * 120, y: baseY + Math.floor(c / 8) * 90 });
        },
        { type, count },
      );

      expect(nodeId, `Node type '${type}' successfully created in store`).toBeTruthy();
      count++;

      // Open inspector / editor for the node to verify React component rendering
      await page.evaluate((id) => {
        window.__uiStore.getState().openNodeEditor?.(id);
      }, nodeId);
      await page.waitForTimeout(20);

      // Close editor cleanly
      await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
    }

    const totalNodesInDom = await page.evaluate(() => document.querySelectorAll('.rf-node').length);
    expect(totalNodesInDom).toBeGreaterThanOrEqual(builtins.length);
    expect(errors, `Uncaught JS errors during builtins audit:\n${errors.join('\n')}`).toEqual([]);
  });

  test('2. Exhaustive Connectors Audit: all 86 enterprise connector types add, render, and inspect without error', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (text.includes('Failed to load resource')) return;
        errors.push(`console.error: ${text}`);
      }
    });

    await setupTestUser(page);

    const connectors: string[] = catalogData.connectors || [];
    expect(connectors.length).toBeGreaterThanOrEqual(80);

    let count = 0;
    for (const type of connectors) {
      const nodeId = await page.evaluate(
        ({ type: t, count: c }) => {
          const store = window.__wfStore.getState();
          const trigger = store.nodes.find((n: any) => n.data?.node?.type === 'manual_trigger');
          const baseX = trigger?.position?.x ?? 0;
          const baseY = trigger?.position?.y ?? 0;
          return store.addNode(t, { x: baseX + 180 + (c % 8) * 130, y: baseY + Math.floor(c / 8) * 90 });
        },
        { type, count },
      );

      expect(nodeId, `Connector '${type}' added to store`).toBeTruthy();
      count++;

      await page.evaluate((id) => {
        window.__uiStore.getState().openNodeEditor?.(id);
      }, nodeId);
      await page.waitForTimeout(20);

      await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
    }

    const totalNodesInDom = await page.evaluate(() => document.querySelectorAll('.rf-node').length);
    expect(totalNodesInDom).toBeGreaterThanOrEqual(connectors.length);
    expect(errors, `Uncaught JS errors during all-connectors audit:\n${errors.join('\n')}`).toEqual([]);
  });

  test('3. Multi-Connector Orchestration: Salesforce, Slack, Gmail, OpenAI, Postgres, and GitHub configured on canvas', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (text.includes('Failed to load resource')) return;
        errors.push(`console.error: ${text}`);
      }
    });

    await setupTestUser(page);

    const orchestrationNodes = [
      { type: 'salesforce', params: { resource: 'Account', operation: 'create', record: { Name: 'Global Logistics Inc' } } },
      { type: 'slack', params: { channel: '#ops-alerts', message: 'New customer account created: Global Logistics Inc' } },
      { type: 'gmail', params: { to: 'ops@flowsmith.local', subject: 'Account Alert', body: 'Account provisioned successfully.' } },
      { type: 'openai', params: { model: 'gpt-4o', prompt: 'Summarize recent enterprise account activity.' } },
      { type: 'postgres', params: { query: 'SELECT id, name FROM accounts WHERE status = $1', values: ['active'] } },
      { type: 'github', params: { operation: 'create_issue', repository: 'org/repo', title: 'Onboard Account' } },
    ];

    let count = 0;
    for (const item of orchestrationNodes) {
      const nodeId = await page.evaluate(
        ({ item, count: c }) => {
          const store = window.__wfStore.getState();
          const id = store.addNode(item.type, { x: 200 + (c % 3) * 260, y: 100 + Math.floor(c / 3) * 160 });
          store.updateNode(id, { parameters: item.params });
          return id;
        },
        { item, count },
      );

      expect(nodeId).toBeTruthy();
      count++;

      // Verify opening inspector and tab switching
      await page.evaluate((id) => {
        window.__uiStore.getState().openNodeEditor?.(id, 'parameters');
      }, nodeId);
      await page.waitForTimeout(30);

      // Verify node parameters persisted in store
      const nodeParams = await page.evaluate((id) => {
        const store = window.__wfStore.getState();
        const n = store.nodes.find((x: any) => x.id === id);
        return n?.data?.node?.parameters;
      }, nodeId);

      expect(nodeParams).toBeDefined();
      await page.evaluate(() => window.__uiStore.getState().closeNodeEditor?.());
    }

    expect(errors, `Uncaught JS errors during multi-connector orchestration:\n${errors.join('\n')}`).toEqual([]);
  });

  test('4. Full Chain Live Execution: Connectors and Flow Nodes wired together and executed live', async ({ page }) => {
    await setupTestUser(page);

    const triggerId = await page.evaluate(() => {
      const store = window.__wfStore.getState();
      const existing = store.nodes.find((n: any) => n.data?.node?.type === 'manual_trigger');
      if (existing) return existing.id;
      return store.addNode('manual_trigger', { x: 80, y: 120 });
    });

    const setVarId = await page.evaluate(() => {
      const store = window.__wfStore.getState();
      const id = store.addNode('set_variable', { x: 280, y: 120 });
      store.updateNode(id, { parameters: { variable_name: 'tenant_id', value: 'acme_enterprise_99' } });
      return id;
    });

    const httpId = await page.evaluate(() => {
      const store = window.__wfStore.getState();
      const id = store.addNode('http_request', { x: 500, y: 120 });
      store.updateNode(id, { parameters: { url: 'http://127.0.0.1:8181/get', method: 'GET' } });
      return id;
    });

    const codeId = await page.evaluate(() => {
      const store = window.__wfStore.getState();
      const id = store.addNode('code', { x: 740, y: 120 });
      store.updateNode(id, { parameters: { code: 'return { status: "processed", count: 1 };' } });
      return id;
    });

    await page.evaluate(
      ({ t, s, h, c }) => {
        const store = window.__wfStore.getState();
        store.onConnect({ source: t, target: s, sourceHandle: 'main', targetHandle: 'main' });
        store.onConnect({ source: s, target: h, sourceHandle: 'main', targetHandle: 'main' });
        store.onConnect({ source: h, target: c, sourceHandle: 'main', targetHandle: 'main' });
      },
      { t: triggerId, s: setVarId, h: httpId, c: codeId },
    );

    await page.waitForTimeout(1000);
    await page.evaluate(() => window.__wfStore.getState().save());
    await page.waitForFunction(
      () => {
        const store = window.__wfStore?.getState();
        return store && !store.saving;
      },
      { timeout: 10000 },
    );

    await page.locator('button.primary--run, button[aria-label="Run workflow"]').first().click();

    // Verify successful node status rings appear on canvas
    await expect(page.locator('.rf-node.status-success')).toHaveCount(4, { timeout: 30000 });
  });
});
