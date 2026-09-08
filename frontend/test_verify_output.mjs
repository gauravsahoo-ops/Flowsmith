import { chromium } from 'playwright'

async function run() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()

  try {
    // Navigate to app
    await page.goto('http://localhost:5173')
    await page.waitForTimeout(1000)

    // Log in or use stored token if required
    const token = await page.evaluate(async () => {
      let t = localStorage.getItem('mat_token')
      if (t) return t
      // Try login
      try {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: 'gauravsahoo15@outlook.com', password: 'password123' })
        })
        if (res.ok) {
          const data = await res.json()
          localStorage.setItem('mat_token', data.access_token || data.token)
          return data.access_token || data.token
        }
      } catch (e) {}
      return null
    })

    console.log('Token ready:', !!token)

    // Navigate to workflow wf_yifzzuth
    await page.goto('http://localhost:5173/workflows/wf_yifzzuth')
    await page.waitForTimeout(2500)

    // Load execution exec_c9dc2706538e in store
    await page.evaluate(async () => {
      // Find execution in zustand store or trigger load
      try {
        const store = window.__executionStore || (window.__DEBUG_STORES__ && window.__DEBUG_STORES__.execution)
        if (store) {
          await store.getState().load('exec_c9dc2706538e')
        }
      } catch (e) {}
    })

    // Double click or open node editor for http_request_2
    const nodeEl = page.locator('[data-id="http_request_2"]').first()
    if (await nodeEl.count() > 0) {
      await nodeEl.dblclick()
    } else {
      // Look for any node with HTTP Request or click node
      const anyNode = page.locator('.react-flow__node').first()
      if (await anyNode.count() > 0) {
        await anyNode.dblclick()
      }
    }

    await page.waitForTimeout(1500)

    // Ensure output tab or check output panel
    const outputPanel = page.locator('.op-container')
    console.log('Output panel present:', await outputPanel.count() > 0)

    // Take screenshot
    await page.screenshot({ path: 'C:/Users/ASUS/.gemini/antigravity-ide/brain/a0b996c1-63f2-4af0-9114-5407245ed713/output_panel_verified.png' })
    console.log('Screenshot saved to output_panel_verified.png')

  } catch (err) {
    console.error('Error in script:', err)
  } finally {
    await browser.close()
  }
}

run()
