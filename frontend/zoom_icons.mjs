import { chromium } from '@playwright/test';
import fs from 'fs';

async function main() {
  const b64_1 = fs.readFileSync('C:/Users/ASUS/.gemini/antigravity-ide/brain/a0b996c1-63f2-4af0-9114-5407245ed713/.user_uploaded/media_1788652225087.png').toString('base64');
  const b64_2 = fs.readFileSync('C:/Users/ASUS/.gemini/antigravity-ide/brain/a0b996c1-63f2-4af0-9114-5407245ed713/.user_uploaded/media_1788652229658.png').toString('base64');

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 450 } });
  const html = `
    <html>
      <body style="background:#18181b; padding:20px; font-family:sans-serif; color:white; display:flex; gap:40px;">
        <div>
          <h3>Loop Over Items (centered)</h3>
          <div style="width:240px; height:240px; overflow:hidden; border:1px solid #444; position:relative; background:#09090b;">
            <img src="data:image/png;base64,${b64_1}" style="image-rendering:pixelated; width:2200px; position:absolute; left:-60px; top:-80px;" />
          </div>
        </div>
        <div>
          <h3>Split Out (centered)</h3>
          <div style="width:240px; height:240px; overflow:hidden; border:1px solid #444; position:relative; background:#09090b;">
            <img src="data:image/png;base64,${b64_2}" style="image-rendering:pixelated; width:2200px; position:absolute; left:-50px; top:-75px;" />
          </div>
        </div>
      </body>
    </html>
  `;
  await page.setContent(html);
  await page.screenshot({ path: 'C:/Users/ASUS/.gemini/antigravity-ide/brain/a0b996c1-63f2-4af0-9114-5407245ed713/scratch/zoomed_both_exact.png' });
  await browser.close();
  console.log('Saved both exact!');
}
main().catch(console.error);
