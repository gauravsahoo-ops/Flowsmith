import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';

async function main() {
  const email = `check2_${Date.now()}@example.com`;
  const pw = 'password123';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  console.log('token ok');

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.goto(base + '/overview');
  await page.waitForLoadState('networkidle');
  console.log('at overview', page.url());

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
    try {
      await page.goto(base + r, { waitUntil: 'networkidle', timeout: 10000 });
      await page.waitForTimeout(400);
      const title = await page.locator('.page-title').first().textContent({ timeout: 3000 }).catch(() => null);
      const url = page.url();
      console.log(`${r} -> ${url} | title: ${title}`);
      if (!title) {
        const body = await page.content();
        console.log('  no title, body snippet', body.slice(0,300));
      }
    } catch (e) {
      console.log(`${r} failed:`, e.message);
    }
  }

  // Test workflow editor
  const listRes = await req.get(`${apiBase}/api/workflows`, { headers: { Authorization: `Bearer ${token}` } });
  const listJson = await listRes.json();
  const wfId = listJson.data?.[0]?.id;
  if (wfId) {
    await page.goto(base + `/workflows/${wfId}`, { waitUntil: 'networkidle', timeout: 10000 });
    await page.waitForTimeout(1000);
    const canvas = await page.locator('.canvas').count();
    console.log(`workflow editor ${wfId} canvas count`, canvas);
    const topbar = await page.locator('.topbar, .workflow-editor-shell .topbar').count();
    console.log('topbar count', topbar);
    // Try opening node editor
    const nodes = await page.evaluate(() => window.__wfStore.getState().nodes.map(n => n.id));
    console.log('nodes', nodes);
    if (nodes.length) {
      await page.evaluate((id) => window.__uiStore.getState().openNodeEditor(id), nodes[0]);
      await page.waitForTimeout(500);
      const modal = await page.locator('.node-editor-modal').count();
      console.log('modal count after open', modal);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
    }
    // Test browser back/forward
    await page.goto(base + '/overview', { waitUntil: 'networkidle' });
    await page.goto(base + `/workflows/${wfId}`, { waitUntil: 'networkidle' });
    await page.goBack();
    console.log('after back', page.url());
    await page.goForward();
    console.log('after forward', page.url());
  }

  // Test sidebar toggle and responsive
  await page.goto(base + '/overview');
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.waitForTimeout(300);
  const sidebarCls = await page.locator('.app-sidebar').getAttribute('class');
  console.log('sidebar class desktop', sidebarCls);
  const toggle = page.locator('.app-sidebar-toggle');
  if (await toggle.count()) {
    await toggle.click();
    await page.waitForTimeout(400);
    console.log('toggled, new class', await page.locator('.app-sidebar').getAttribute('class'));
  }
  // Mobile
  await page.setViewportSize({ width: 500, height: 800 });
  await page.waitForTimeout(300);
  console.log('mobile sidebar', await page.locator('.app-sidebar').getAttribute('class'));
  const hamburger = page.locator('.app-topbar-hamburger');
  console.log('hamburger count mobile', await hamburger.count());
  if (await hamburger.count()) {
    await hamburger.click();
    await page.waitForTimeout(400);
    console.log('mobile drawer open', await page.locator('.app-sidebar').getAttribute('class'));
  }

  await browser.close();
  await req.dispose();
  console.log('done');
}

main().catch(e => { console.error(e); process.exit(1); });
