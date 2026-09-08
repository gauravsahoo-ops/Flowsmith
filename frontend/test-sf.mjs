import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `sf_test_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  // Create a workflow
  const wfId = `wf_sf_${Date.now()}`;
  await req.post(`${apiBase}/api/workflows`, { data: { id: wfId, name: 'SF Test', nodes: [{id:'trigger', type:'manual_trigger', position:{x:0,y:0}, parameters:{}}], connections:[], settings:{} }, headers: { Authorization: `Bearer ${token}` } });
  await page.goto(`${base}/workflows/${wfId}`);
  await page.waitForSelector('.canvas', { timeout: 10000 });
  await page.waitForTimeout(1000);
  // Check palette has Salesforce
  const hasSf = await page.locator('.sidebar').textContent().then(t => t.includes('Salesforce'));
  console.log('Palette has Salesforce?', hasSf);
  // Click Salesforce to open browser (the connector, not trigger) - use last match
  const sfRows = page.locator('.node-palette:has-text("Salesforce")');
  console.log('Salesforce row count', await sfRows.count());
  const sfRow = sfRows.last();
  if (await sfRow.count()) {
    await sfRow.click();
    await page.waitForTimeout(500);
    const browserVisible = await page.locator('.sf-browser').count();
    console.log('Salesforce browser visible?', browserVisible);
    if (browserVisible) {
      const searchVisible = await page.locator('.sf-browser-search input').count();
      console.log('Search visible?', searchVisible);
      const triggersText = await page.locator('.sf-section').first().textContent().then(t=>t.slice(0,100));
      console.log('First section', triggersText);
      // Test search - try generic terms that match our 10 operations
      await page.locator('.sf-browser-search input').fill('create');
      await page.waitForTimeout(300);
      console.log('After search create, ops count', await page.locator('.sf-op-item').count());
      await page.locator('.sf-browser-search input').fill('account');
      await page.waitForTimeout(300);
      console.log('After search account, ops count', await page.locator('.sf-op-item').count(), '(expected 0 for generic ops)');
      await page.locator('.sf-browser-search input').fill('');
      await page.waitForTimeout(300);
      // Click an action that has Additional Fields (Create Record)
      const createBtn = page.locator('.sf-op-item:has-text("Create Record")');
      console.log('Create Record count', await createBtn.count());
      if (await createBtn.count()) {
        await createBtn.click();
      } else {
        const actionSection = page.locator('.sf-section').nth(1);
        const firstAction = actionSection.locator('.sf-op-item').first();
        console.log('First action', await firstAction.textContent().then(t=>t.slice(0,60)).catch(()=>'none'));
        if (await firstAction.count()) {
          await firstAction.click();
        } else {
          const firstOp = page.locator('.sf-op-item').first();
          console.log('Fallback first op', await firstOp.textContent().then(t=>t.slice(0,60)));
          await firstOp.click();
        }
      }
      await page.waitForTimeout(1000);
      const modalVisible = await page.locator('.node-editor-modal').count();
      console.log('Modal visible after op select?', modalVisible);
      if (modalVisible) {
        console.log('Modal header', await page.locator('.nem-header h2').textContent().then(t=>t.slice(0,50)));
        // Check Additional Fields
        const addFieldBtn = page.locator('button:has-text("+ Add Field")');
        console.log('Add Field btn count', await addFieldBtn.count());
        if (await addFieldBtn.count()) {
          await addFieldBtn.first().click();
          await page.waitForTimeout(300);
          console.log('Picker visible?', await page.locator('.sf-field-picker').count());
          const firstField = page.locator('.sf-field-picker-list li button').first();
          console.log('First field', await firstField.textContent().then(t=>t.slice(0,50)).catch(()=> 'none'));
          if (await firstField.count()) {
            await firstField.click();
            await page.waitForTimeout(300);
            console.log('After add field, field rows', await page.locator('.sf-field-row').count());
            const removeBtn = page.locator('.sf-field-remove').first();
            console.log('Remove btn', await removeBtn.count());
            if (await removeBtn.count()) {
              await removeBtn.click();
              await page.waitForTimeout(300);
              console.log('After remove, rows', await page.locator('.sf-field-row').count());
            }
          }
        }
        await page.keyboard.press('Escape');
      }
    }
  }
  await browser.close();
  await req.dispose();
  console.log('done');
}
main().catch(e=>{console.error(e); process.exit(1)});
