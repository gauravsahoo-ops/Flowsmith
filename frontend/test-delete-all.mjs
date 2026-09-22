import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `test_del_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const headers = { Authorization: `Bearer ${token}` };
  // create a workflow with 2 nodes
  const wfId = `wf_${Date.now()}`;
  const wf = {
    id: wfId,
    name: 'Delete Test',
    nodes: [
      {id:'n1', type:'manual_trigger', position:{x:0,y:0}, parameters:{}},
      {id:'n2', type:'set_data', position:{x:200,y:0}, parameters:{fields:{}}},
    ],
    connections: [{source:'n1', target:'n2'}],
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
  console.log('Initial nodes:', await page.evaluate(() => window.__wfStore.getState().nodes.length));
  // Try to delete all nodes via store
  await page.evaluate(() => {
    const store = window.__wfStore.getState();
    const ids = store.nodes.map(n=>n.id);
    console.log('Deleting', ids);
    store.deleteNodes(ids);
  });
  await page.waitForTimeout(1000);
  const afterCount = await page.evaluate(() => window.__wfStore.getState().nodes.length);
  const error = await page.evaluate(() => window.__wfStore.getState().error);
  console.log('After delete all attempt, nodes:', afterCount);
  console.log('Error:', error);
  // Check canvas still has nodes or shows empty state
  const canvasEmpty = await page.locator('.canvas-empty-state').count();
  console.log('Canvas empty overlay:', canvasEmpty);
  const banner = await page.locator('.banner, .banner-inline').first().textContent().catch(()=> 'no banner');
  console.log('Banner:', banner.slice(0,200));
  // Try select-all + Delete via keyboard
  await page.keyboard.press('Control+A');
  await page.waitForTimeout(200);
  await page.keyboard.press('Delete');
  await page.waitForTimeout(1000);
  const afterCount2 = await page.evaluate(() => window.__wfStore.getState().nodes.length);
  console.log('After Ctrl+A Delete, nodes:', afterCount2);
  const error2 = await page.evaluate(() => window.__wfStore.getState().error);
  console.log('Error2:', error2);
  // Check that workflow can still be saved after adding a node
  await page.evaluate(() => window.__wfStore.getState().addNode('set_data', {x:300,y:0}));
  await page.waitForTimeout(600);
  const afterAdd = await page.evaluate(() => window.__wfStore.getState().nodes.length);
  console.log('After add node, nodes:', afterAdd);
  const saving = await page.evaluate(() => window.__wfStore.getState().saving);
  console.log('Saving:', saving);
  await browser.close();
  await req.dispose();
  console.log('done');
}
main().catch(e=>{console.error(e); process.exit(1)});
