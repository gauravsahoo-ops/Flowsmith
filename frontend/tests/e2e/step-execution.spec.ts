/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

const API = 'http://localhost:8000';

function auth(token: string) {
  return { Authorization: `Bearer ${token}` };
}

test.describe('Step-through Execution (Previous & Execute Step)', () => {
  test('Execute Step runs a single node and Previous runs upstream chain', async ({ page }) => {
    const email = `step_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@example.com`;
    const password = 'P@ssword1';

    // 1. Register & login via API
    await page.request.post(`${API}/api/auth/register`, { data: { email, password } });
    const lr = await page.request.post(`${API}/api/auth/login`, { data: { email, password } });
    const { data: { token } } = await lr.json();
    const headers = auth(token);

    // 2. Create the 3-node test workflow directly via API for determinism
    const wfId = `wf_step_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const createRes = await page.request.post(`${API}/api/workflows`, {
      headers,
      data: {
        id: wfId,
        name: 'Step Execution Test WF',
        nodes: [
          { id: 'trigger', type: 'manual_trigger', parameters: {}, position: { x: 50, y: 100 } },
          {
            id: 'code_1',
            type: 'code',
            parameters: {
              code: 'return [{ greeting: "hello from step", step_val: 100 }]',
              language: 'javascript',
            },
            position: { x: 300, y: 100 },
          },
          {
            id: 'code_2',
            type: 'code',
            parameters: {
              code: 'return [{ transformed: $json.step_val * 3 }]',
              language: 'javascript',
            },
            position: { x: 550, y: 100 },
          },
        ],
        connections: [
          { source: 'trigger', target: 'code_1', sourceHandle: 'main', targetHandle: 'main' },
          { source: 'code_1', target: 'code_2', sourceHandle: 'main', targetHandle: 'main' },
        ],
      },
    });
    expect(createRes.ok()).toBeTruthy();

    // 3. Set token in localStorage and navigate to the workflow editor
    await page.goto('http://localhost:5173');
    await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
    await page.reload();
    await page.waitForLoadState('networkidle').catch(() => {});

    await page.goto(`http://localhost:5173/workflows/${wfId}`);
    await page.waitForLoadState('networkidle').catch(() => {});

    // Wait for the store and workflow to be loaded
    await page.waitForFunction(
      () => {
        const s = window.__wfStore?.getState();
        return s && !s.loading && s.workflow;
      },
      { timeout: 15000 },
    );

    // 4. Open the node editor modal for code_1
    await page.evaluate(() => {
      window.__uiStore?.getState().openNodeEditor('code_1');
    });

    const modal = page.locator('.node-editor-modal');
    await expect(modal).toBeVisible({ timeout: 10000 });

    // 5. Test "Execute Step" on code_1
    const executeStepBtn = modal.locator('header button:has-text("Execute Step")');
    await expect(executeStepBtn).toBeVisible();
    await executeStepBtn.click();

    // Verify code_1 execution succeeds
    await expect(modal.locator('.nem-title-status .status-badge')).toHaveText(/success/i, { timeout: 20000 });

    // Verify output panel displays code_1 returned data
    await expect(modal.locator('.nem-output')).toContainText('hello from step', { timeout: 10000 });
    await expect(modal.locator('.nem-output')).toContainText('100');

    // 6. Switch editor to downstream node (code_2)
    await page.evaluate(() => {
      window.__uiStore?.getState().openNodeEditor('code_2');
    });

    await expect(modal).toBeVisible({ timeout: 10000 });

    // 7. Test "Previous" button on code_2
    const previousBtn = modal.locator('header button:has-text("Previous")');
    await expect(previousBtn).toBeVisible();
    await previousBtn.click();

    // Verify the previous upstream node data (from code_1) appears in code_2's Input tab
    await expect(modal.locator('.nem-input')).toContainText('hello from step', { timeout: 20000 });

    // 8. Test "Execute Step" on code_2 now that input is seeded
    await executeStepBtn.click();

    // Verify second node execution succeeds with transformed data (100 * 3 = 300)
    await expect(modal.locator('.nem-title-status .status-badge')).toHaveText(/success/i, { timeout: 20000 });
    await expect(modal.locator('.nem-output')).toContainText('300', { timeout: 10000 });
  });
});
