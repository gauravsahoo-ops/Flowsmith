/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';
import * as path from 'path';

const ARTIFACT_DIR = 'C:/Users/ASUS/.gemini/antigravity-ide/brain/eb30052b-77a7-4c0f-abd8-2ab99b2d7324';

test('system browser audit: login, overview, integrations marketplace, ai copilot, workflows', async ({ page }) => {
  test.setTimeout(90000);

  // 1. Visit Login Page
  await page.goto('http://localhost:5173');
  await page.waitForLoadState('networkidle').catch(() => {});

  // Take screenshot of Login page
  await page.screenshot({ path: `${ARTIFACT_DIR}/login_page_audit.png`, fullPage: true });

  // 2. Log in using admin credentials
  const emailInput = page.locator('input[type="email"]');
  const passwordInput = page.locator('input[type="password"]');

  if (await emailInput.isVisible()) {
    await emailInput.fill('admin@flowsmith.io');
    await passwordInput.fill('Admin123!');
    await page.locator('button[type="submit"]').click();
  }

  // Wait for redirect to overview
  await page.waitForURL('**/overview', { timeout: 15000 });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);

  // Take screenshot of Overview Dashboard
  await page.screenshot({ path: `${ARTIFACT_DIR}/overview_page_audit.png`, fullPage: true });

  // 3. Test Integrations Marketplace (/integrations)
  await page.goto('http://localhost:5173/integrations');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);

  // Verify Marketplace elements
  const searchInput = page.locator('.marketplace-search input');
  await expect(searchInput).toBeVisible();
  
  // Wait for connector cards to load from backend
  await page.locator('.connector-card').first().waitFor({ state: 'visible', timeout: 15000 });
  const cards = page.locator('.connector-card');
  const cardCount = await cards.count();
  expect(cardCount).toBeGreaterThan(10);

  // Take screenshot of Integrations Marketplace
  await page.screenshot({ path: `${ARTIFACT_DIR}/integrations_marketplace_audit.png`, fullPage: true });

  // Test opening a connector detail drawer
  const firstCard = cards.first();
  await firstCard.click();
  await page.waitForTimeout(500);

  // Verify drawer is open
  const drawer = page.locator('.connector-drawer');
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/integrations_drawer_audit.png`, fullPage: true });

  // Close drawer
  const closeBtn = page.locator('.drawer-close');
  if (await closeBtn.isVisible()) {
    await closeBtn.click();
  } else {
    await page.keyboard.press('Escape');
  }
  await expect(page.locator('.connector-drawer')).not.toBeVisible();
  await page.waitForTimeout(300);

  // Test OpenAPI Import Modal
  const importBtn = page.getByRole('button', { name: /Import OpenAPI/i });
  await expect(importBtn).toBeVisible();
  await importBtn.click();
  await page.waitForTimeout(400);

  const openApiModal = page.locator('.oai-modal-window');
  await expect(openApiModal).toBeVisible();
  await page.screenshot({ path: `${ARTIFACT_DIR}/openapi_import_modal_audit.png` });

  // Close modal via Escape key
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await expect(openApiModal).not.toBeVisible();

  // 4. Test AI Copilot Page (/ai)
  await page.goto('http://localhost:5173/ai');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${ARTIFACT_DIR}/ai_copilot_page_audit.png`, fullPage: true });

  // 5. Test Workflows Page (/workflows)
  await page.goto('http://localhost:5173/workflows');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${ARTIFACT_DIR}/workflows_page_audit.png`, fullPage: true });

  // 6. Test Data Tables (/data-tables)
  await page.goto('http://localhost:5173/data-tables');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${ARTIFACT_DIR}/datatables_page_audit.png`, fullPage: true });

  console.log('Browser audit completed successfully with all screenshots saved to artifacts directory.');
});
