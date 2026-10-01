import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

const ARTIFACT_DIR = 'C:/Users/ASUS/.gemini/antigravity-ide/brain/1b1dbbe9-670b-4a9e-ad3b-6aefbe438d36';

test('Verify Run Mock simulation and Open in Canvas import', async ({ page }) => {
  // 1. Obtain auth token for user 4
  let token = '';
  try {
    token = execSync(
      `c:\\Flowsmith\\.venv\\Scripts\\python.exe -c "from app.db import SessionLocal; from app.models import User; from app.security.jwt import create_token; db=SessionLocal(); u=db.query(User).filter_by(id=4).first(); print(create_token(u.id, u.email))"`,
      { cwd: 'c:\\Flowsmith\\backend' }
    ).toString().trim();
  } catch (err) {
    console.error('Failed to get token:', err);
  }

  // 2. Set token and navigate to AI Builder tab
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);

  const testBlueprint = {
    workflow: {
      id: 'wf_e2e_lead_enrich',
      name: 'Salesforce Lead Enrichment & Scoring',
      nodes: [
        {
          id: 'lead_trigger',
          type: 'webhook',
          name: 'Salesforce Lead Trigger',
          position: { x: 100, y: 180 },
          parameters: { path: 'salesforce-lead-hook-12345678', http_method: 'POST' },
          credentials: {},
        },
        {
          id: 'enrich_company',
          type: 'http_request',
          name: 'Clearbit Company Enrichment',
          position: { x: 380, y: 180 },
          parameters: { url: 'https://api.clearbit.com/v2/companies/find', method: 'GET' },
          credentials: { custom_auth: '$user' },
        },
        {
          id: 'update_sf',
          type: 'salesforce',
          name: 'Update Salesforce Lead',
          position: { x: 660, y: 180 },
          parameters: { operation: 'update' },
          credentials: { salesforce: '$user' },
        },
      ],
      connections: [
        { source: 'lead_trigger', target: 'enrich_company', sourceHandle: 'main', targetHandle: 'main' },
        { source: 'enrich_company', target: 'update_sf', sourceHandle: 'main', targetHandle: 'main' },
      ],
      settings: {},
    },
    plan: [
      { id: '1', title: 'Ingest Salesforce Lead Event', description: 'Receive lead trigger' },
      { id: '2', title: 'Enrich with Clearbit API', description: 'Fetch company domain attributes' },
      { id: '3', title: 'Update Salesforce CRM', description: 'Persist lead updates' },
    ],
  };

  // Mock intent and generate-workflow endpoints so test is instant and deterministic
  await page.route('**/api/ai/intent', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          intent: {
            name: 'Salesforce Lead Enrichment',
            goal: 'Enrich leads and sync',
            trigger: { kind: 'webhook', system: 'salesforce', config: {} },
            steps: [
              { id: 'enrich_company', kind: 'http', system: 'clearbit', name: 'Enrich Company', inputs: {} },
              { id: 'update_sf', kind: 'action', system: 'salesforce', name: 'Update Lead', inputs: { operation: 'update' } },
            ],
            connections: [{ source: 'enrich_company', target: 'update_sf' }],
          },
          missing_info: [],
        },
        meta: {},
      }),
    });
  });

  await page.route('**/api/ai/generate-workflow', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: testBlueprint,
        meta: {},
      }),
    });
  });

  await page.goto('http://localhost:5173/ai?tab=builder');
  await page.waitForLoadState('networkidle').catch(() => {});

  // Click the starter prompt to fill text
  await page.locator('button:has-text("Salesforce Lead Enrichment")').click();

  // Click Synthesize
  await page.locator('button:has-text("Synthesize & Validate Workflow")').click();

  // 3. Verify Run Mock button appears
  const runMockBtn = page.locator('button:has-text("▶ Run Mock")');
  await expect(runMockBtn).toBeVisible({ timeout: 15000 });

  // Click Run Mock
  await runMockBtn.click();

  // Verify simulation result rendered
  await expect(page.locator('text=Simulation completed across 3 nodes')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Clearbit Company Enrichment').first()).toBeVisible({ timeout: 5000 });

  // Take screenshot of Run Mock trace
  await page.screenshot({ path: `${ARTIFACT_DIR}/run_mock_trace_verified.png`, fullPage: true });

  // 4. Click "Open in Canvas ↗"
  const openCanvasBtn = page.locator('button:has-text("Open in Canvas ↗")');
  await expect(openCanvasBtn).toBeVisible();
  await openCanvasBtn.click();

  // Verify successful redirection to /workflows/wf_import_...
  await page.waitForURL(/\/workflows\/wf_import_/, { timeout: 15000 });
  await page.waitForTimeout(2000);

  // Verify NO error banner
  await expect(page.locator('text=Failed to import to canvas')).not.toBeVisible();

  // Verify canvas loaded
  await expect(page.locator('.react-flow, [data-testid="rf__wrapper"]')).toBeVisible({ timeout: 10000 });

  // Take screenshot of canvas
  await page.screenshot({ path: `${ARTIFACT_DIR}/open_in_canvas_verified.png`, fullPage: true });
});
