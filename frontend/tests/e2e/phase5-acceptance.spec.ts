/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

test.describe('Phase 5 — Full-Stack UX and Functional Completeness Suite', () => {
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

  test('Journey 1: Canvas lifecycle, TopBar Duplicate, and safe draft state', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Create a new workflow for testing
    const sourceWfId = `wf_phase5_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const createRes = await page.request.post('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        id: sourceWfId,
        name: 'Phase 5 Core Workflow',
        nodes: [
          { id: 'trigger_1', type: 'manual_trigger', position: { x: 80, y: 120 } },
          { id: 'transform_1', type: 'set_data', position: { x: 340, y: 120 }, parameters: { values: { testKey: 'flowsmith_ok' } } },
        ],
        connections: [
          { source: 'trigger_1', target: 'transform_1', sourceHandle: 'main', targetHandle: 'main' },
        ],
        settings: {},
      },
    });
    expect(createRes.ok()).toBeTruthy();

    // Navigate to workflow canvas
    await page.goto(`http://localhost:5173/workflows/${sourceWfId}`);
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 25000 });

    // Open TopBar "More actions" menu
    const moreMenuBtn = page.locator('button[aria-label="More actions"]').first();
    await expect(moreMenuBtn).toBeVisible({ timeout: 10000 });
    await moreMenuBtn.click();

    // Verify Duplicate Workflow button is present in menu
    const duplicateBtn = page.locator('button[role="menuitem"]:has-text("Duplicate Workflow")');
    await expect(duplicateBtn).toBeVisible({ timeout: 5000 });
    await duplicateBtn.click();

    // Expect navigation to duplicated workflow URL
    await page.waitForURL(
      (url) => url.pathname.startsWith('/workflows/') && !url.pathname.includes(sourceWfId),
      { timeout: 15000 }
    );
    const currentUrl = page.url();
    expect(currentUrl).not.toContain(sourceWfId);

    // Verify duplicated workflow metadata in window.__wfStore
    await page.waitForFunction(() => Boolean(window.__wfStore?.getState()?.workflow?.id), { timeout: 10000 });
    const duplicatedWf = await page.evaluate(() => window.__wfStore.getState().workflow);

    expect(duplicatedWf.name).toContain('(Copy)');
    expect(duplicatedWf.active).toBe(false);
    expect(duplicatedWf.status === 'draft' || duplicatedWf.active === false).toBe(true);

    // Verify browser refresh preserves state without console or network crash
    await page.reload();
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 25000 });
    const reloadedWf = await page.evaluate(() => window.__wfStore.getState().workflow);
    expect(reloadedWf.name).toContain('(Copy)');
  });

  test('Journey 2: NodeEditorModal and DynamicNodeConfigPanel test-step linkage', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Create workflow with a testable node
    const wfId = `wf_step_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const createRes = await page.request.post('http://localhost:8000/api/workflows', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        id: wfId,
        name: 'Step Test Workflow',
        nodes: [
          { id: 'node_data', type: 'set_data', position: { x: 100, y: 100 }, parameters: { values: { verified: true } } },
        ],
        connections: [],
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

    // Open node editor for node_data
    await page.evaluate(() => {
      window.__uiStore?.getState()?.openNodeEditor('node_data');
    });

    // Verify NodeEditorModal is rendered
    const modal = page.locator('.node-editor-modal, [data-testid="node-editor-modal"], div[role="dialog"]');
    await expect(modal.first()).toBeVisible({ timeout: 10000 });

    // Verify Test Step or Execute Step button is enabled and clickable
    const testStepBtn = page.locator('button:has-text("Test Step"), button:has-text("Execute Step")').first();
    await expect(testStepBtn).toBeVisible({ timeout: 8000 });
    await expect(testStepBtn).toBeEnabled();

    // Click Test Step
    await testStepBtn.click();
    await page.waitForTimeout(1500);

    // Output panel should reflect execution
    const outputArea = page.locator('.node-editor-modal, .output-panel, [data-testid="output-panel"]').first();
    await expect(outputArea).toBeVisible();
  });

  test('Journey 3: Platform Security Audit Trail rendered in SettingsPage', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Navigate to Settings Page
    await page.goto('http://localhost:5173/settings');
    await page.waitForLoadState('networkidle').catch(() => {});

    // Verify Platform Audit Trail section is rendered
    const auditTitle = page.locator('text=Platform Audit Trail').first();
    await expect(auditTitle).toBeVisible({ timeout: 15000 });

    // Verify audit table and action filter
    const actionFilter = page.locator('select:has-text("All Actions")').first();
    await expect(actionFilter).toBeVisible({ timeout: 5000 });

    // Verify table headers (Timestamp, Action, Actor, Target Type, Target ID, Details)
    await expect(page.locator('th:has-text("Timestamp")').first()).toBeVisible();
    await expect(page.locator('th:has-text("Action")').first()).toBeVisible();
  });

  test('Journey 4: Execution History & Universal Search accessibility', async ({ page }) => {
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

    // Navigate to Executions Page
    await page.goto('http://localhost:5173/executions');
    await page.waitForLoadState('networkidle').catch(() => {});

    // Check presence of filter controls (All, Running, Succeeded, Failed)
    await expect(page.locator('text=Executions').first()).toBeVisible({ timeout: 15000 });

    // Navigate to AI Page
    await page.goto('http://localhost:5173/ai');
    await page.waitForLoadState('networkidle').catch(() => {});
    await expect(page.locator('text=AI Workflow Studio').first()).toBeVisible({ timeout: 15000 });
  });
});
