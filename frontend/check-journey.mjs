import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `journey_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  // create org/ws for data tables
  const org = await req.post(`${apiBase}/api/organizations`, { data: { name: `Org${Date.now()}` }, headers: { Authorization: `Bearer ${token}` } }).then(r=>r.json()).then(j=>j.data);
  const ws = await req.post(`${apiBase}/api/workspaces`, { data: { name: `WS${Date.now()}`, organization_id: org.id }, headers: { Authorization: `Bearer ${token}` } }).then(r=>r.json()).then(j=>j.data);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.goto(base + '/overview');
  await page.waitForLoadState('networkidle');
  console.log('1 Overview', await page.locator('.page-title').first().textContent());
  await page.goto(base + '/workflows');
  await page.waitForLoadState('networkidle');
  console.log('2 Personal/Workflows', await page.locator('.page-title').first().textContent());
  // search
  await page.locator('.search-input').first().fill('My');
  await page.waitForTimeout(300);
  console.log('3 Search done');
  // sort
  await page.locator('select').first().selectOption('name');
  await page.waitForTimeout(300);
  console.log('4 Sort done');
  // filter
  await page.locator('select').nth(1).selectOption('all');
  await page.waitForTimeout(300);
  console.log('5 Filter done');
  // open workflow
  const wfList = await req.get(`${apiBase}/api/workflows`, { headers: { Authorization: `Bearer ${token}` } }).then(r=>r.json()).then(j=>j.data);
  const wfId = wfList[0]?.id;
  console.log('wfId', wfId);
  await page.goto(base + `/workflows/${wfId}`);
  await page.waitForLoadState('networkidle');
  await page.waitForSelector('.canvas', { timeout: 10000 });
  console.log('6 Workflow editor canvas visible', await page.locator('.canvas').count());
  console.log('7 Top bar visible', await page.locator('.topbar--workflow').count());
  // add node
  await page.evaluate(() => window.__wfStore.getState().addNode('set_data', { x: 300, y: 100 }));
  await page.waitForTimeout(500);
  const nodes = await page.evaluate(() => window.__wfStore.getState().nodes.map(n=>n.id));
  console.log('8 Add node', nodes.length);
  const newNode = nodes.find(id => id.includes('set_data'));
  await page.locator(`.rf-node:has-text("${newNode}")`).first().click();
  await page.waitForSelector('.node-editor-modal', { timeout: 5000 });
  console.log('9 Centered Node Editor visible', await page.locator('.node-editor-modal').count());
  console.log('10 Input', await page.locator('.nem-panel.nem-input').count());
  console.log('11 Parameters', await page.locator('.nem-panel.nem-params').count());
  console.log('12 Output', await page.locator('.nem-panel.nem-output').count());
  // close editor
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  console.log('13 Close editor', await page.locator('.node-editor-modal').count() ? 'still open' : 'closed');
  // execute
  await page.locator('.primary--run').first().click();
  await page.waitForTimeout(2000);
  console.log('14 Execute clicked');
  // debugger
  await page.evaluate((id) => window.__uiStore.getState().openNodeEditor(id), newNode);
  await page.waitForTimeout(500);
  await page.keyboard.press('Escape');
  console.log('15 Debugger via execution inspector', await page.locator('.inspector, .debugger').count());
  // history
  await page.goto(base + '/executions');
  await page.waitForLoadState('networkidle');
  console.log('16 History', await page.locator('.page-title').first().textContent());
  // back to workflows
  await page.goto(base + '/workflows');
  await page.waitForLoadState('networkidle');
  console.log('17 Return to list', await page.locator('.page-title').first().textContent());
  // test data tables
  await page.goto(base + '/data-tables');
  await page.waitForLoadState('networkidle');
  console.log('18 Data Tables', await page.locator('.page-title').first().textContent());
  // test variables, knowledge etc
  await page.goto(base + '/variables');
  console.log('19 Variables', await page.locator('.page-title').first().textContent());
  await page.goto(base + '/knowledge');
  console.log('20 Knowledge', await page.locator('.page-title').first().textContent());
  await browser.close();
  await req.dispose();
  console.log('journey done');
}
main().catch(e=>{console.error(e); process.exit(1)});
