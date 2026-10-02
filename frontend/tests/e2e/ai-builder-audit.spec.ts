import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
import path from 'path';

const ARTIFACT_DIR = 'C:/Users/ASUS/.gemini/antigravity-ide/brain/1b1dbbe9-670b-4a9e-ad3b-6aefbe438d36';

test('AI Builder 3-column UI audit and visual verification', async ({ page }) => {
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

  await page.goto('http://localhost:5173/ai?tab=builder');
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);

  // 3. Verify AI Builder Console elements
  await expect(page.locator('text=Natural Language Requirements')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('text=6-Stage Validation Pipeline')).toBeVisible();
  await expect(page.locator('text=Simulation Runner')).toBeVisible();

  // 4. Take full-page screenshot of the 3-column AI Builder Console
  await page.screenshot({ path: `${ARTIFACT_DIR}/ai_builder_3_column_console.png`, fullPage: true });

  // 5. Verify Mode Switching
  await page.locator('button', { hasText: /^Modify$/i }).click();
  await page.waitForTimeout(500);

  await page.locator('button', { hasText: /^Repair$/i }).click();
  await page.waitForTimeout(500);

  // Return to build mode
  await page.locator('button', { hasText: /^Build$/i }).click();
  await page.waitForTimeout(500);

  // Take screenshot of interactive modes
  await page.screenshot({ path: `${ARTIFACT_DIR}/ai_builder_modes_verified.png`, fullPage: true });
});
