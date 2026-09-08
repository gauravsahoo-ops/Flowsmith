import { chromium } from 'playwright';
import { request } from 'playwright';

const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';

async function main() {
  const email = `check_${Date.now()}@example.com`;
  const pw = 'password123';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  console.log('token', token.slice(0,20));

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  console.log('current url', page.url());

  const routes = [
    '/overview',
    '/workflows',
    '/credentials',
    '/executions',
    '/templates',
    '/variables',
    '/knowledge',
    '/approvals',
    '/shared',
    '/billing',
    '/settings',
    '/help',
  ];

  for (const r of routes) {
    await page.goto(base + r);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    const title = await page.locator('.page-title, h1').first().textContent().catch(() => 'no title');
    const hasContent = await page.locator('.page, .app-content').first().isVisible().catch(() => false);
    console.log(`${r} -> ${page.url()} | title: ${String(title).slice(0,60)} | visible: ${hasContent}`);
    // check for errors
    const err = await page.locator('.banner-inline.err').first().textContent().catch(() => null);
    if (err) console.log('  error banner:', err.slice(0,100));
  }

  // Test workflow list and open
  await page.goto(base + '/workflows');
  await page.waitForLoadState('networkidle');
  const wfCount = await page.locator('.data-table tbody tr').count().catch(() => 0);
  console.log('workflows count', wfCount);
  // Test sidebar collapse
  await page.goto(base + '/overview');
  await page.waitForLoadState('networkidle');
  const sidebar = page.locator('.app-sidebar');
  console.log('sidebar exists', await sidebar.count());
  // Check collapsed state
  const toggle = page.locator('.app-sidebar-toggle');
  if (await toggle.count()) {
    await toggle.click();
    await page.waitForTimeout(300);
    console.log('toggled sidebar');
    const cls = await sidebar.getAttribute('class');
    console.log('sidebar class after toggle', cls);
  }
  // Test global search
  await page.keyboard.press('Control+K');
  await page.waitForTimeout(500);
  const searchVisible = await page.locator('.global-search, .palette').count();
  console.log('global search visible after Ctrl+K', searchVisible);
  await page.keyboard.press('Escape');
  await browser.close();
  await req.dispose();
  console.log('done');
}

main().catch(e => { console.error(e); process.exit(1); });
