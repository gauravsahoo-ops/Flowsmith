import { chromium } from 'playwright'

async function run() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  const email = `test_${Date.now()}@example.com`
  const password = 'P@ssword1'

  await page.request.post('http://localhost:8000/api/auth/register', {
    data: { email, password },
  })
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { email, password },
  })
  const { data: { token } } = await loginRes.json()

  await page.goto('http://localhost:5173')
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token)
  await page.reload()
  await page.waitForLoadState('networkidle')

  const wfRes = await page.request.post('http://localhost:8000/api/workflows', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      id: `wf_test_${Date.now()}`,
      name: 'Output Inspection Test',
      nodes: [
        { id: 'trigger_1', type: 'manual_trigger', position: { x: 100, y: 150 }, parameters: {}, settings: {} },
        { 
          id: 'http_1', 
          type: 'http_request', 
          position: { x: 350, y: 150 }, 
          parameters: { 
            url: 'https://httpbin.org/get',
            method: 'GET'
          }, 
          settings: {} 
        }
      ],
      connections: [
        { source: 'trigger_1', target: 'http_1' }
      ],
      settings: {}
    }
  })
  const wfJson = await wfRes.json()
  const wfId = wfJson.data?.id

  await page.goto(`http://localhost:5173/workflows/${wfId}`)
  await page.waitForSelector('.topbar--workflow', { timeout: 15000 })

  const nodeEl = await page.waitForSelector('[data-id="http_1"]')
  await nodeEl.dblclick()
  await page.waitForTimeout(1000)

  const execBtn = await page.waitForSelector('.nem-empty-btn, button:has-text("Execute Step")')
  if (execBtn) {
    await execBtn.click()
  }

  await page.waitForTimeout(5000)

  // 1. Schema Tab
  const outputPanel = await page.waitForSelector('.nem-panel.nem-output')
  const schemaTab = await outputPanel.waitForSelector('.nem-input-tab:has-text("Schema")')
  await schemaTab.click()
  await page.waitForTimeout(600)

  const outPath1 = 'C:\\Users\\ASUS\\.gemini\\antigravity-ide\\brain\\a0b996c1-63f2-4af0-9114-5407245ed713\\.tempmediaStorage\\output_panel_schema.png'
  await page.screenshot({ path: outPath1 })
  console.log('Saved schema screenshot to:', outPath1)

  // 2. Click Table Tab inside .nem-panel.nem-output
  const tableTab = await outputPanel.waitForSelector('.nem-input-tab:has-text("Table")')
  await tableTab.click()
  await page.waitForTimeout(600)

  const outPath2 = 'C:\\Users\\ASUS\\.gemini\\antigravity-ide\\brain\\a0b996c1-63f2-4af0-9114-5407245ed713\\.tempmediaStorage\\output_panel_table.png'
  await page.screenshot({ path: outPath2 })
  console.log('Saved table screenshot to:', outPath2)

  // 3. Click JSON Tab inside .nem-panel.nem-output
  const jsonTab = await outputPanel.waitForSelector('.nem-input-tab:has-text("JSON")')
  await jsonTab.click()
  await page.waitForTimeout(600)

  const outPath3 = 'C:\\Users\\ASUS\\.gemini\\antigravity-ide\\brain\\a0b996c1-63f2-4af0-9114-5407245ed713\\.tempmediaStorage\\output_panel_json.png'
  await page.screenshot({ path: outPath3 })
  console.log('Saved JSON screenshot to:', outPath3)

  await browser.close()
}

run().catch(err => {
  console.error(err)
  process.exit(1)
})
