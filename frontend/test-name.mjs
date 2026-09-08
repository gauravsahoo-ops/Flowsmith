import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `test_name_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const headers = { Authorization: `Bearer ${token}` };
  const wfId = `wf_${Date.now()}`;
  const wf = {
    id: wfId,
    name: 'Test Name',
    nodes: [{id:'n1', type:'manual_trigger', position:{x:0,y:0}, parameters:{}}],
    connections: [],
    settings: {}
  };
  await req.post(`${apiBase}/api/workflows`, { data: wf, headers });
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.goto(`${base}/workflows/${wfId}`);
  await page.waitForSelector('.canvas', { timeout: 10000 });
  await page.waitForTimeout(1000);
  console.log('Initial name:', await page.evaluate(() => window.__wfStore.getState().workflow.name));
  // Delete all name
  const input = page.locator('.workflow-name');
  await input.click();
  await input.press('Control+A');
  await input.press('Backspace');
  await page.waitForTimeout(200);
  console.log('After delete, input value:', await input.inputValue());
  console.log('Store name:', await page.evaluate(() => window.__wfStore.getState().workflow.name));
  // Wait for auto-save (500ms debounce + API)
  await page.waitForTimeout(1500);
  const error = await page.evaluate(() => window.__wfStore.getState().error);
  console.log('Error after save:', error);
  const savedAt = await page.evaluate(() => window.__wfStore.getState().savedAt);
  console.log('SavedAt:', savedAt);
  // Check via API
  const get = await req.get(`${apiBase}/api/workflows/${wfId}`, { headers });
  console.log('GET workflow:', get.status(), await get.text().then(t=>t.slice(0,500)));
  const list = await req.get(`${apiBase}/api/workflows`, { headers });
  const listJson = await list.json();
  console.log('List workflows:', listJson.data.map(w=>({id:w.id, name:JSON.stringify(w.name)})));
  await browser.close();
  await req.dispose();
  console.log('done');
}
main().catch(e=>{console.error(e); process.exit(1)});
