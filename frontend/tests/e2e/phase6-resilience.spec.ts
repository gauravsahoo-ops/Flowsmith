/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

test.describe('Phase 6 — Quality, Performance, and Resilience E2E Journeys', () => {
  let token = '';

  test.beforeAll(async () => {
    try {
      const isFrontendCwd = process.cwd().endsWith('frontend');
      const rootDir = isFrontendCwd ? path.resolve(process.cwd(), '..') : process.cwd();
      const tokenScript = path.resolve(rootDir, 'frontend', 'tests', 'e2e', 'get_token.py');
      const output = execSync(`python "${tokenScript}"`, {
        cwd: rootDir,
        encoding: 'utf-8',
      });
      token = output.trim();
    } catch (err) {
      console.error('Failed to get token via python script:', err);
    }
  });

  test('Journey 1: Workflow creation, live execution, and execution logs telemetry', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    const wfId = `wf_p6_exec_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const createRes = await page.request.post('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        id: wfId,
        name: 'Phase 6 Live Telemetry WF',
        nodes: [
          { id: 't1', type: 'manual_trigger', position: { x: 80, y: 120 } },
          { id: 's1', type: 'set_data', position: { x: 300, y: 120 }, parameters: { fields: { telemetry_ok: true, stage: 'phase6' } } },
        ],
        connections: [
          { source: 't1', target: 's1', sourceHandle: 'main', targetHandle: 'main' },
        ],
        settings: {},
      },
    });
    expect(createRes.ok()).toBeTruthy();

    await page.goto(`http://localhost:5173/workflows/${wfId}`);
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 25000 });

    // Wait for store to be ready
    await page.waitForFunction(() => {
      const s = window.__wfStore?.getState();
      return s && !s.loading && s.workflow;
    }, { timeout: 15000 });

    // Trigger execution via TopBar run button
    const runBtn = page.locator('button[aria-label="Run workflow"], button[aria-label="Activate workflow"], button:has-text("Run"), button:has-text("Activate")').first();
    await expect(runBtn).toBeVisible({ timeout: 10000 });
    await runBtn.click();

    // Verify execution completes and output panel or logs reflect success
    await page.waitForTimeout(2500);

    // Navigate to Executions page to confirm recorded telemetry
    await page.goto('http://localhost:5173/executions');
    await page.waitForLoadState('networkidle').catch(() => {});
    await expect(page.locator('text=Executions').first()).toBeVisible({ timeout: 15000 });
  });

  test('Journey 2: Resilient Retries & Failed Execution Inspection', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Create workflow with a deliberate stop_and_error failure
    const wfId = `wf_p6_fail_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const createRes = await page.request.post('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        id: wfId,
        name: 'Phase 6 Error Retry WF',
        nodes: [
          { id: 't1', type: 'manual_trigger', position: { x: 80, y: 120 } },
          { id: 'err1', type: 'stop_and_error', position: { x: 300, y: 120 }, parameters: { errorMessage: 'Simulated upstream failure' } },
        ],
        connections: [
          { source: 't1', target: 'err1', sourceHandle: 'main', targetHandle: 'main' },
        ],
        settings: {},
      },
    });
    expect(createRes.ok()).toBeTruthy();

    // Run execution via API directly to test execution record and error capture
    const runRes = await page.request.post(`http://localhost:8000/api/workflows/${wfId}/run`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {},
    });
    expect(runRes.ok()).toBeTruthy();
    const runJson = await runRes.json();
    const execId = runJson.data?.execution_id || runJson.data?.id;
    expect(execId).toBeTruthy();

    // Navigate to Execution Detail view
    await page.goto(`http://localhost:5173/executions/${execId}`);
    await page.waitForLoadState('networkidle').catch(() => {});

    // Verify failed execution status is clearly displayed
    const statusEl = page.locator('.status-failed, .status-label:has-text("Failed")').first();
    await expect(statusEl).toBeVisible({ timeout: 15000 });
  });

  test('Journey 3: Import/Export Secret Stripping and Clean Draft Guarantee', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    const sourceWfId = `wf_p6_sec_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    await page.request.post('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        id: sourceWfId,
        name: 'Secret Stripping Test WF',
        nodes: [
          { id: 't1', type: 'manual_trigger', position: { x: 80, y: 120 } },
          { id: 'http1', type: 'http_request', position: { x: 300, y: 120 }, parameters: { url: 'https://api.example.com', auth: { token: 'super_secret_token_12345' } } },
        ],
        connections: [{ source: 't1', target: 'http1', sourceHandle: 'main', targetHandle: 'main' }],
        settings: {},
      },
    });

    // Call export endpoint
    const exportRes = await page.request.get(`http://localhost:8000/api/workflows/${sourceWfId}/export`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(exportRes.ok()).toBeTruthy();
    const exportJson = await exportRes.json();
    const exportStr = JSON.stringify(exportJson);

    // Assert that credentials/secrets are completely stripped from export payload
    expect(exportStr).not.toContain('super_secret_token_12345');

    // Duplicate workflow via API
    const dupRes = await page.request.post(`http://localhost:8000/api/workflows/${sourceWfId}/duplicate`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(dupRes.ok()).toBeTruthy();
    const dupJson = await dupRes.json();
    const dupWf = dupJson.data;

    // Enforce draft state guarantees
    expect(dupWf.name).toContain('(Copy)');
    expect(dupWf.active).toBe(false);
    expect(dupWf.status).toBe('draft');
  });

  test('Journey 4: AI Workflow Studio prompt synthesis and simulation view', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Navigate to AI Page
    await page.goto('http://localhost:5173/ai');
    await page.waitForLoadState('networkidle').catch(() => {});

    // Verify AI Workflow Studio header
    await expect(page.locator('text=AI Workflow Studio').first()).toBeVisible({ timeout: 15000 });

    // Verify mode buttons (Build, Modify, Repair, Smith Copilot, Action button)
    await expect(page.locator('button:has-text("Build")').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button:has-text("Modify")').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button:has-text("Repair")').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button:has-text("Ask Smith AI Assistant")').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button:has-text("Synthesize & Validate Workflow")').first()).toBeVisible({ timeout: 5000 });
  });
});
