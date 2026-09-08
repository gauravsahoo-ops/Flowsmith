import { chromium, request } from 'playwright';
const base = 'http://127.0.0.1:5173';
const apiBase = 'http://127.0.0.1:8000';
async function main() {
  const email = `test_menu_${Date.now()}@example.com`;
  const pw = 'Password123!';
  const req = await request.newContext();
  await req.post(`${apiBase}/api/auth/register`, { data: { email, password: pw } });
  const login = await req.post(`${apiBase}/api/auth/login`, { data: { email, password: pw } });
  const { data: { token } } = await login.json();
  const headers = { Authorization: `Bearer ${token}` };
  // create org/ws for data tables? Not needed for workflow list.
  // Create 10 workflows
  for (let i=0;i<10;i++) {
    const id = `wf_test_${Date.now()}_${i}_${Math.random().toString(36).slice(2,6)}`;
    await req.post(`${apiBase}/api/workflows`, { data: { id, name: `Workflow ${i+1}`, nodes: [{id:'trigger', type:'manual_trigger', position:{x:0,y:0}, parameters:{}}], connections:[], settings:{} }, headers });
  }
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(base);
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.goto(base + '/workflows');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
  // Check table exists
  const rows = page.locator('.data-table tbody tr');
  const count = await rows.count();
  console.log('Workflow rows:', count);
  if (count < 5) { console.log('Not enough workflows, found', count); }
  // Test first tile
  const firstBtn = page.locator('button[aria-label="More actions"]').first();
  const firstRow = page.locator('.data-table tbody tr').first();
  const firstBoxBefore = await firstRow.boundingBox();
  await firstBtn.click();
  await page.waitForTimeout(300);
  let menu = page.locator('.context-menu--portal');
  let menuCount = await menu.count();
  console.log('Menu after first click count:', menuCount);
  let menuBox = await menu.boundingBox();
  console.log('First menu box:', menuBox);
  let firstBoxAfter = await firstRow.boundingBox();
  console.log('First row height before/after', firstBoxBefore?.height, firstBoxAfter?.height);
  if (firstBoxBefore?.height !== firstBoxAfter?.height) console.log('FAIL: layout shift!');
  else console.log('PASS: no layout shift');
  // Check menu is outside tile: menu should not be inside row
  const isInsideRow = await page.evaluate(() => {
    const menu = document.querySelector('.context-menu--portal');
    const row = document.querySelector('.data-table tbody tr');
    return row && menu && row.contains(menu);
  });
  console.log('Menu inside row?', isInsideRow ? 'FAIL: clipped' : 'PASS: outside');
  // Check menu not clipped by table-wrap overflow
  const tableWrapBox = await page.locator('.table-wrap').boundingBox();
  const insideWrap = menuBox && tableWrapBox && menuBox.x >= tableWrapBox.x && menuBox.x + menuBox.width <= tableWrapBox.x + tableWrapBox.width && menuBox.y >= tableWrapBox.y;
  console.log('Table wrap box:', tableWrapBox);
  console.log('Menu outside table-wrap clipping?', menuBox && tableWrapBox && (menuBox.y + menuBox.height > tableWrapBox.y + tableWrapBox.height ? 'maybe outside (good, portal)' : 'inside'));
  // Check menu above tiles (z-index)
  const menuZ = await menu.evaluate(el => window.getComputedStyle(el).zIndex);
  console.log('Menu z-index:', menuZ);
  // Test middle tile
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  const middleBtn = page.locator('button[aria-label="More actions"]').nth(Math.floor(count/2));
  await middleBtn.click();
  await page.waitForTimeout(300);
  console.log('Middle menu count:', await page.locator('.context-menu--portal').count());
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  // Test last tile (should flip above)
  const lastBtn = page.locator('button[aria-label="More actions"]').last();
  await lastBtn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  const lastRowBoxBefore = await page.locator('.data-table tbody tr').last().boundingBox();
  await lastBtn.click();
  await page.waitForTimeout(300);
  const lastMenuBox = await page.locator('.context-menu--portal').boundingBox();
  console.log('Last menu box:', lastMenuBox);
  console.log('Last row box:', lastRowBoxBefore);
  if (lastMenuBox && lastRowBoxBefore) {
    const flipped = lastMenuBox.y < lastRowBoxBefore.y;
    console.log('Last menu flipped above?', flipped ? 'yes (good)' : 'no (maybe enough space below)');
  }
  // Test scroll
  await page.evaluate(() => document.querySelector('.app-content')?.scrollTo(0, 200));
  await page.waitForTimeout(300);
  const afterScrollBox = await page.locator('.context-menu--portal').boundingBox();
  console.log('After scroll menu box (should reposition):', afterScrollBox);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  console.log('After ESC menu count:', await page.locator('.context-menu--portal').count());
  // Test outside click
  await firstBtn.click();
  await page.waitForTimeout(300);
  await page.mouse.click(10, 10);
  await page.waitForTimeout(300);
  console.log('After outside click menu count:', await page.locator('.context-menu--portal').count());
  // Test click another ⋮ switches
  await firstBtn.click();
  await page.waitForTimeout(300);
  const secondBtn = page.locator('button[aria-label="More actions"]').nth(1);
  await secondBtn.click();
  await page.waitForTimeout(300);
  console.log('After clicking second, menu count:', await page.locator('.context-menu--portal').count());
  const secondMenuBox = await page.locator('.context-menu--portal').boundingBox();
  console.log('Second menu box:', secondMenuBox);
  // Test responsive
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(500);
  await firstBtn.click();
  await page.waitForTimeout(300);
  const mobileBox = await page.locator('.context-menu--portal').boundingBox();
  console.log('Mobile menu box:', mobileBox, 'viewport 375');
  if (mobileBox) {
    const insideViewport = mobileBox.x >= 0 && mobileBox.x + mobileBox.width <= 375;
    console.log('Mobile inside viewport?', insideViewport ? 'PASS' : 'FAIL');
  }
  await browser.close();
  await req.dispose();
  console.log('done');
}
main().catch(e=>{console.error(e); process.exit(1)});
