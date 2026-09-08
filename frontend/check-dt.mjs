import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `checkdt_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.goto(base + '/data-tables');
  await page.waitForLoadState('networkidle');
  console.log('url', page.url());
  console.log('title', await page.locator('.page-title').first().textContent());
  console.log('workspace tabs', await page.locator('.workspace-tabs').count());
  console.log('table count', await page.locator('.data-table tbody tr').count().catch(()=>0));
  // Try to create a table via API then reload
  const h = { Authorization: `Bearer ${token}` };
  let org = await req.post(`${apiBase}/api/organizations`, { data: { name: `Org${Date.now()}` }, headers: h }).then(r=>r.json()).then(j=>j.data);
  // Actually org creation needs handle
  const orgRes = await req.post(`${apiBase}/api/organizations`, { data: { name: `Org${Date.now()}${Math.random()}` }, headers: h });
  const orgJson = await orgRes.json();
  console.log('org', orgJson);
  const wsRes = await req.post(`${apiBase}/api/workspaces`, { data: { name: `WS${Date.now()}`, organization_id: orgJson.data.id }, headers: h });
  const wsJson = await wsRes.json();
  console.log('ws', wsJson);
  const wsId = wsJson.data.id;
  const tblRes = await req.post(`${apiBase}/api/data-tables`, { data: { name: 'Customers', description: 'Test', workspace_id: wsId, columns: [{name:'name', type:'string', required:true},{name:'email',type:'string'}] }, headers: h });
  console.log('create tbl', await tblRes.json());
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
  console.log('after reload title', await page.locator('.page-title').first().textContent());
  console.log('rows', await page.locator('.data-table tbody tr').count());
  // Open table
  const tblId = (await tblRes.json()).data.id;
  await page.goto(base + `/data-tables/${tblId}`);
  await page.waitForLoadState('networkidle');
  console.log('editor url', page.url());
  console.log('editor title', await page.locator('.page-title').first().textContent());
  console.log('columns', await page.locator('.data-table').count());
  // Test adding row via UI? Just check API
  const rowRes = await req.post(`${apiBase}/api/data-tables/${tblId}/rows`, { data: { data: { name: 'Alice', email: 'a@b.com' } }, headers: h });
  console.log('insert row', await rowRes.json());
  await page.reload();
  await page.waitForTimeout(1000);
  console.log('after insert count', await page.locator('.data-table tbody tr').count());
  // Test workflow node
  const wfId = `wf_${Date.now()}`;
  const wf = {
    id: wfId,
    name: 'DT WF',
    nodes: [
      {id:'trigger', type:'manual_trigger', position:{x:0,y:0}, parameters:{}},
      {id:'dt1', type:'data_table', position:{x:100,y:0}, parameters:{table_id: tblId, operation:'select'}}
    ],
    connections: [{source:'trigger', target:'dt1'}],
    settings: {}
  };
  const wfRes = await req.post(`${apiBase}/api/workflows`, { data: wf, headers: h });
  console.log('wf create', await wfRes.json());
  const runRes = await req.post(`${apiBase}/api/workflows/${wfId}/run`, { data: {}, headers: h });
  console.log('run', await runRes.json());
  await browser.close();
  await req.dispose();
}
main().catch(e=>{console.error(e); process.exit(1)});
