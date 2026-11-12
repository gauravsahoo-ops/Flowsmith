/// <reference path="./global.d.ts" />
import { expect, test } from '@playwright/test'

/**
 * Regression: a workflow opened for the first time must hydrate and render
 * its nodes without requiring a browser refresh.
 */
test('workflow editor renders on first load without a refresh', async ({ page }) => {
  const email = `first_load_${Date.now()}@example.com`
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
      name: `First Load ${Date.now()}`,
      nodes: [
        { id: 'trigger', type: 'manual_trigger', position: { x: 160, y: 160 }, parameters: {} },
        { id: 'set1', type: 'set_data', position: { x: 460, y: 160 }, parameters: { fields: { ok: true } } },
      ],
      connections: [{ source: 'trigger', target: 'set1' }],
      settings: {},
    },
  })
  const workflowId = (await created.json()).data.id

  await page.goto('http://localhost:5173')
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token)
  await page.goto(`http://localhost:5173/workflows/${workflowId}`)

  // No page.reload() here: the initial hydration must be sufficient.
  await expect(page.locator('.react-flow__node')).toHaveCount(2, { timeout: 15000 })
  await expect(page.locator('.workflow-name')).toHaveValue(/First Load/)

  const state = await page.evaluate(() => {
    const store = window.__wfStore.getState()
    return {
      workflowId: store.workflow?.id,
      hydratedId: store.hydratedId,
      nodeCount: store.nodes.length,
    }
  })
  expect(state.workflowId).toBe(workflowId)
  expect(state.hydratedId).toBe(workflowId)
  expect(state.nodeCount).toBe(2)
})
