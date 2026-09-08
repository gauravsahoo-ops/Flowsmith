import { chromium } from 'playwright'

async function run() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })

  const email = `test_${Date.now()}@example.com`
  const password = 'P@ssword1'

  // Register & login
  await page.request.post('http://localhost:8000/api/auth/register', { data: { email, password } })
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', { data: { email, password } })
  const { data: { token } } = await loginRes.json()

  await page.goto('http://localhost:5173')
  await page.evaluate((t) => {
    localStorage.setItem('mat_token', t)
    localStorage.setItem('workflow_logs_open', 'false') // Ensure collapsed initially
  }, token)

  // Create workflow
  const wfRes = await page.request.post('http://localhost:8000/api/workflows', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      id: `wf_${Date.now()}`,
      name: 'Teams to Salesforce Sync',
      nodes: [{ id: 'trigger_1', type: 'manual_trigger', position: { x: 100, y: 150 }, parameters: {}, settings: {} }],
      connections: [],
      settings: {},
    },
  })
  const { data: wf } = await wfRes.json()

  await page.goto(`http://localhost:5173/workflows/${wf.id}`)
  await page.waitForSelector('.topbar--workflow', { timeout: 15000 })

  // 1. Initially collapsed
  const dock = await page.waitForSelector('.logs-dock.collapsed')
  console.log('Dock is initially collapsed:', dock !== null)

  // 2. Click "Input" button while collapsed
  const inputBtn = await page.waitForSelector('.logs-tab-btn.input')
  console.log('Clicking Input button...')
  await inputBtn.click()

  // Verify dock expands and switches to Input!
  await page.waitForSelector('.logs-dock.expanded', { timeout: 3000 })
  await page.waitForSelector('.logs-tab-btn.input.active', { timeout: 3000 })
  console.log('PASS: Dock auto-expanded and redirected to Input tab!')

  // 3. Click "Output" button
  const outputBtn = await page.waitForSelector('.logs-tab-btn.output')
  console.log('Clicking Output button...')
  await outputBtn.click()

  await page.waitForSelector('.logs-tab-btn.output.active', { timeout: 3000 })
  console.log('PASS: Redirected to Output tab!')

  // 4. Click "Logs" button
  const logsBtn = await page.waitForSelector('.logs-tab-btn:has-text("Logs")')
  console.log('Clicking Logs button...')
  await logsBtn.click()

  await page.waitForSelector('.logs-tab-btn:has-text("Logs").active', { timeout: 3000 })
  console.log('PASS: Redirected to Logs tab!')

  // Take screenshot of expanded Output tab
  await outputBtn.click()
  await page.waitForTimeout(300)
  const shotPath = 'C:\\Users\\ASUS\\.gemini\\antigravity-ide\\brain\\a0b996c1-63f2-4af0-9114-5407245ed713\\.tempmediaStorage\\logs_tab_auto_redirect.png'
  await page.screenshot({ path: shotPath })
  console.log('Saved screenshot to:', shotPath)

  await browser.close()
  console.log('All tab redirect tests passed successfully!')
}

run().catch(err => {
  console.error(err)
  process.exit(1)
})
