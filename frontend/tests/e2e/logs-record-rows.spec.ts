/// <reference path="./global.d.ts" />
import { expect, test } from '@playwright/test'

/**
 * Regression: the execution log stream renders individual records and its
 * search box filters them, instead of showing only a whole batch row.
 */
test('execution logs render records one by one and search them', async ({ page }) => {
  const email = `logs_records_${Date.now()}@example.com`
  const password = 'P@ssword1'

  await page.request.post('http://localhost:8000/api/auth/register', {
    data: { email, password },
  })
  const loginRes = await page.request.post('http://localhost:8000/api/auth/login', {
    data: { email, password },
  })
  const { data: { token } } = await loginRes.json()
  const auth = { Authorization: `Bearer ${token}` }

  const created = await page.request.post('http://localhost:8000/api/workflows', {
    headers: auth,
    data: {
      name: `Logs Records ${Date.now()}`,
      nodes: [
        { id: 'trigger', type: 'manual_trigger', position: { x: 160, y: 160 }, parameters: {} },
        { id: 'hs1', type: 'hubspot', position: { x: 460, y: 160 }, parameters: {} },
      ],
      connections: [{ source: 'trigger', target: 'hs1' }],
      settings: {},
    },
  })
  const workflowId = (await created.json()).data.id

  await page.goto('http://localhost:5173')
  await page.evaluate((t) => {
    localStorage.setItem('mat_token', t)
    localStorage.setItem('workflow_logs_open', 'true')
  }, token)
  await page.goto(`http://localhost:5173/workflows/${workflowId}`)
  await expect(page.locator('.react-flow__node')).toHaveCount(2, { timeout: 15000 })

  // Seed a completed run: one connector step carrying two records, plus a
  // per-item trace row. This is the shape the backend now emits.
  await page.evaluate(() => {
    const now = new Date().toISOString()
    ;(window.__execStore as { setState: (patch: Record<string, unknown>) => void }).setState({
      executionId: 'exec_logs_test',
      running: false,
      status: 'success',
      error: null,
      results: { outputs: {}, inputs: {} },
      nodeStatuses: { hs1: 'success' },
      trace: [
        {
          node_id: 'hs1',
          node_type: 'hubspot',
          status: 'success',
          started_at: now,
          duration_ms: 12,
          note: 'Search Record',
          inputs: { main: [{ object_type: 'cars' }] },
          outputs: {
            main: [{
              records: [
                { id: '1', properties: { email: 'alice@example.com', model: 'Roadster' } },
                { id: '2', properties: { email: 'bob@example.com', model: 'Cybertruck' } },
              ],
            }],
          },
        },
        {
          node_id: 'hs1',
          node_type: 'hubspot',
          status: 'success',
          started_at: now,
          duration_ms: 4,
          item_index: 2,
          item_total: 3,
          note: 'Record 2/3.',
          inputs: { main: [{ email: 'second@example.com' }] },
          outputs: { main: [{ id: '3', email: 'second@example.com' }] },
        },
      ],
    })
  })

  const stream = page.locator('.logs-stream')
  await expect(stream).toContainText('Record 2/3.', { timeout: 10000 })

  // The connector step expands its records as child rows.
  const showRecords = stream.getByRole('button', { name: /Show 2 records/i })
  await expect(showRecords).toBeVisible()
  await showRecords.click()
  await expect(page.locator('.logs-record-row')).toHaveCount(2)
  await expect(page.locator('.logs-record-row').first()).toContainText('alice@example.com')

  // Search filters both node rows and record rows.
  const searchToggle = page.locator('.logs-sub-toolbar--logs .logs-search-toggle')
  await searchToggle.click()
  await page.getByLabel('Search execution logs').fill('cybertruck')

  await expect(page.locator('.logs-record-row')).toHaveCount(1, { timeout: 5000 })
  await expect(page.locator('.logs-record-row')).toContainText('bob@example.com')
  await expect(page.getByTestId('logs-search-count')).toContainText('1 record')
})
