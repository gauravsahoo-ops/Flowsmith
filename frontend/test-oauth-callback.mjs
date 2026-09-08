import { chromium } from 'playwright';
const base = 'http://127.0.0.1:5173';
async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(base + '/oauth/callback?provider=salesforce&ok=1');
  await page.waitForLoadState('networkidle');
  const text = await page.textContent('body');
  console.log('Body text:', text.slice(0,500));
  console.log('Has success?', text.includes('Connection successful') ? 'yes' : 'no');
  console.log('Has closing?', text.includes('Closing') ? 'yes' : 'no');
  // Test error case
  await page.goto(base + '/oauth/callback?provider=salesforce&ok=0&error=test%20error');
  await page.waitForLoadState('networkidle');
  const text2 = await page.textContent('body');
  console.log('Error body:', text2.slice(0,500));
  console.log('Has failed?', text2.includes('Connection failed') ? 'yes' : 'no');
  await browser.close();
}
main().catch(e=>{console.error(e); process.exit(1)});
