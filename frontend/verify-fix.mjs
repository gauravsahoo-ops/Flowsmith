import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `verify_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  // get workflow
  const list = await req.get(`${apiBase}/api/workflows`, { headers: { Authorization: `Bearer ${token}` } }).then(r=>r.json()).then(j=>j.data);
  let wfId = list[0]?.id;
  if (!wfId) {
    // create one via API
    const wf = { id: `wf_${Date.now()}`, name: 'Verify WF', nodes: [{id:'trigger', type:'manual_trigger', position:{x:0,y:0}, parameters:{}}], connections:[], settings:{} };
    const res = await req.post(`${apiBase}/api/workflows`, { data: wf, headers: { Authorization: `Bearer ${token}` } }).then(r=>r.json());
    wfId = res.data.id;
  }
  await page.goto(`${base}/workflows/${wfId}`);
  await page.waitForSelector('.canvas', { timeout: 10000 });
  await page.waitForTimeout(1000);
  const configCount = await page.locator('.panel').count();
  const inspectorCount = await page.locator('.inspector, .debugger').count();
  const canvasBox = await page.locator('.canvas').boundingBox();
  const sidebarCount = await page.locator('.sidebar').count();
  console.log('1. Config panel count (should be 0 for normal state, debugger hidden):', configCount);
  console.log('   Debugger panel count (should be 0 when no execution, hidden):', inspectorCount);
  console.log('   Sidebar (palette) count:', sidebarCount);
  console.log('   Canvas bbox width', canvasBox?.width);
  // Check no permanent debugger: canvas should be wide > 600
  if (canvasBox && canvasBox.width < 500) console.log('FAIL: canvas too narrow, still squeezed by permanent panels');
  else console.log('PASS: canvas width ok');

  // Click node
  const nodeId = await page.evaluate(() => window.__wfStore.getState().nodes[0]?.id);
  console.log('nodeId', nodeId);
  await page.locator(`.rf-node:has-text("${nodeId}")`).first().click();
  await page.waitForSelector('.node-editor-modal', { timeout: 5000 });
  console.log('2. Centered Node Editor opened:', await page.locator('.node-editor-modal').count());
  console.log('   Input panel', await page.locator('.nem-panel.nem-input').count());
  console.log('   Parameters panel', await page.locator('.nem-panel.nem-params').count());
  console.log('   Output panel', await page.locator('.nem-panel.nem-output').count());
  // Check Data Table node not fake: list nodes catalog
  const catalog = await page.evaluate(() => window.__wfStore.getState().catalog.map(n=>n.type));
  console.log('3. Catalog has data_table?', catalog.includes('data_table'));
  // Verify data_table node execution is real (we tested backend, but check UI palette)
  const paletteText = await page.locator('.sidebar').textContent().catch(()=> '');
  console.log('   Palette has Data Table?', paletteText.includes('Data Table'));
  // Close editor
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  console.log('4. After close, canvas still visible:', await page.locator('.canvas').count());
  console.log('   Modal closed:', await page.locator('.node-editor-modal').count() === 0 ? 'yes' : 'no');
  // Execute
  await page.evaluate(() => window.__wfStore.getState().addNode('set_data', {x:200,y:100}));
  await page.waitForTimeout(500);
  await page.locator('.primary--run').first().click();
  await page.waitForTimeout(3000);
  const debuggerHidden = await page.locator('.debugger').count();
  console.log('5. After execute, debugger still hidden (should be 0, contextual):', debuggerHidden);
  // Open debugger explicitly
  const dbgBtn = page.locator('button:has-text("Debugger")');
  console.log('   Debugger button exists', await dbgBtn.count());
  if (await dbgBtn.count()) {
    await dbgBtn.click();
    await page.waitForTimeout(500);
    console.log('6. After clicking Debugger, debugger visible:', await page.locator('.debugger').count());
    console.log('   Canvas still wide?', (await page.locator('.canvas').boundingBox())?.width);
    await page.locator('.debugger-backdrop').click().catch(()=> page.keyboard.press('Escape'));
    await page.waitForTimeout(500);
    console.log('7. After closing debugger, debugger hidden:', await page.locator('.debugger').count() === 0 ? 'yes' : 'no');
  }
  await browser.close();
  await req.dispose();
}
main().catch(e=>{console.error(e); process.exit(1)});
