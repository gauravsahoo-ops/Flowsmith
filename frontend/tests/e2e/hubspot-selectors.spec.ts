/// <reference path="./global.d.ts" />
import { expect, test } from '@playwright/test'

/**
 * Regression: HubSpot operation/method and object pickers are searchable,
 * and custom objects returned by live discovery are selectable.
 */
test('HubSpot operation and object selectors search and select', async ({ page }) => {
  const email = `hubspot_select_${Date.now()}@example.com`
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
      name: `HubSpot Select ${Date.now()}`,
      nodes: [
        { id: 'trigger', type: 'manual_trigger', position: { x: 160, y: 160 }, parameters: {} },
        {
          id: 'hs1',
          type: 'hubspot',
          position: { x: 460, y: 160 },
          parameters: { operation: 'search', object_type: 'contacts', search_field: 'email', search_value: 'a@b.com' },
          credentials: {},
        },
      ],
      connections: [{ source: 'trigger', target: 'hs1' }],
      settings: {},
    },
  })
  const workflowId = (await created.json()).data.id

  // Live discovery requires a real portal in production. This spec pins the
  // response so the picker's search/selection behaviour is deterministic.
  await page.route('**/api/connectors/hubspot/objects**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          objects: [
            { key: 'contacts', label: 'Contacts', is_custom: false, object_type_id: null },
            { key: 'cars', label: 'Cars', is_custom: true, object_type_id: '2-12345678' },
            { key: 'invoices', label: 'Invoices', is_custom: true, object_type_id: '2-87654321' },
          ],
          count: 3,
          standard_count: 1,
          custom_count: 2,
          custom_objects_available: true,
          custom_error: null,
          cached: false,
        },
      }),
    })
  })

  await page.goto('http://localhost:5173')
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token)
  await page.goto(`http://localhost:5173/workflows/${workflowId}`)
  await expect(page.locator('.react-flow__node')).toHaveCount(2, { timeout: 15000 })

  // 0. The node palette search must find "HubSpot methods" (operation labels
  //    are part of the connector's searchable text).
  const openPalette = page.locator('.sidebar-unhide-btn')
  if (await openPalette.isVisible().catch(() => false)) await openPalette.click()
  const paletteSearch = page.getByPlaceholder('Search nodes...')
  await expect(paletteSearch).toBeVisible({ timeout: 5000 })
  await paletteSearch.fill('hubspot methods')
  await expect(page.locator('.node-palette', { hasText: 'HubSpot' }).first()).toBeVisible({ timeout: 5000 })
  await paletteSearch.fill('')

  const nodeId = await page.evaluate(() => {
    const store = window.__wfStore.getState()
    return store.nodes.find((n) => n.data?.node?.type === 'hubspot')?.id
  })
  expect(nodeId).toBeTruthy()
  await page.evaluate((id) => window.__uiStore.getState().openNodeEditor(id), nodeId)
  await expect(page.locator('.node-editor-modal')).toBeVisible({ timeout: 10000 })

  // 1. Operation/method search: "HubSpot methods" must find the connector's
  //    operations even though their labels do not contain "methods".
  const operationSelect = page.locator('[data-testid="dncp-operation-select"] .searchable-select')
  await operationSelect.getByRole('button').first().click()
  const operationSearch = operationSelect.getByRole('textbox')
  await operationSearch.fill('hubspot methods')
  const operationOption = operationSelect.getByRole('option', { name: /Search Record/i }).first()
  await expect(operationOption).toBeVisible({ timeout: 5000 })
  await operationOption.click()

  await expect
    .poll(() => page.evaluate(() => {
      const store = window.__wfStore.getState()
      const node = store.nodes.find((n) => n.data?.node?.type === 'hubspot')
      return node?.data?.node?.parameters?.operation
    }))
    .toBe('search')

  // 2. Object search: custom objects from discovery are searchable and
  //    selectable, not just the hard-coded standard list.
  const objectSelect = page.locator('[data-testid="dncp-select-object_type"] .searchable-select')
  await objectSelect.getByRole('button').first().click()
  const objectSearch = objectSelect.getByRole('textbox')
  await objectSearch.fill('cars')
  const objectOption = objectSelect.getByRole('option', { name: /Cars/i }).first()
  await expect(objectOption).toBeVisible({ timeout: 5000 })
  await objectOption.click()

  await expect
    .poll(() => page.evaluate(() => {
      const store = window.__wfStore.getState()
      const node = store.nodes.find((n) => n.data?.node?.type === 'hubspot')
      return node?.data?.node?.parameters?.object_type
    }))
    .toBe('cars')
})
