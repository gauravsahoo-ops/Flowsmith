/// <reference path="./global.d.ts" />
import { test, expect } from '@playwright/test';

const API = 'http://localhost:8000';
const STUB = 'http://127.0.0.1:8181';

function auth(token: string) { return { Authorization: `Bearer ${token}` }; }

async function gotoApp(page: any, token: string) {
  await page.goto('http://localhost:5173');
  await page.evaluate((t) => localStorage.setItem('mat_token', t), token);
  await page.reload();
  await page.waitForLoadState('networkidle').catch(() => {});
  try {
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 5000 });
  } catch {
    const listRes = await page.request.get(`${API}/api/workflows`, { headers: auth(token) });
    const listJson = await listRes.json();
    const wfId = listJson.data?.[0]?.id;
    if (wfId) {
      await page.goto(`http://localhost:5173/workflows/${wfId}`);
      await page.waitForLoadState('networkidle').catch(() => {});
    }
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
  }
}

async function addHttpNodeAndConnect(page: any, url: string, method = 'GET', extra: Record<string, any> = {}) {
  await page.evaluate(({ url, method, extra }) => {
    const store = window.__wfStore.getState();
    const existingHttpIds = new Set(
      store.nodes.filter((n: any) => n.data?.node?.type === 'http_request').map((n: any) => n.id)
    );
    if (existingHttpIds.size > 0) {
      window.__wfStore.setState({
        nodes: store.nodes.filter((n: any) => !existingHttpIds.has(n.id)),
        edges: store.edges.filter((e: any) => !existingHttpIds.has(e.source) && !existingHttpIds.has(e.target)),
      });
    }
    const currentStore = window.__wfStore.getState();
    const triggerId = currentStore.nodes.find((n: any) => n.data?.node?.type === 'manual_trigger')?.id;
    currentStore.addNode('http_request', { x: 300, y: 0 });
    const httpNode = window.__wfStore.getState().nodes.filter((n: any) => n.data?.node?.type === 'http_request').pop();
    window.__wfStore.getState().updateNode(httpNode.id, { parameters: { method, url, ...extra } });
    window.__wfStore.getState().onConnect({ source: triggerId, target: httpNode.id, sourceHandle: 'main', targetHandle: 'main' });
  }, { url, method, extra });
}

async function saveAndRun(page: any) {
  await page.waitForTimeout(1000);
  await page.evaluate(() => window.__wfStore.getState().save());
  await page.waitForFunction(() => { const s = (window as any).__wfStore?.getState(); return s && !s.saving; }, { timeout: 15000 });
  await page.locator('button.primary--run, button[aria-label="Run workflow"]').first().click();
  await expect(page.locator('.topbar .run-status.status-success')).toHaveText('success', { timeout: 60000 });
}

async function getTrace(page: any, token: string) {
  const execWfId = await page.evaluate(() => window.__wfStore.getState().workflow.id);
  const eres = await page.request.get(`${API}/api/executions?workflow_id=${execWfId}&pageSize=5`, { headers: auth(token) });
  const list = (await eres.json()).data;
  const execId = list.find((e: any) => e.workflow_id === execWfId && e.status === 'success')?.id;
  const tr = await page.request.get(`${API}/api/executions/${execId}/trace`, { headers: auth(token) });
  return (await tr.json()).data.steps;
}

function httpSteps(steps: any[]) { return steps.filter((s: any) => s.node_type === 'http_request' && s.status === 'success'); }
function lastOutput(steps: any[]) { return httpSteps(steps).pop()?.outputs.main[0]; }

async function registerAndLogin(page: any) {
  const email = `sf_${Date.now()}_${Math.random().toString(36).slice(2,6)}@example.com`;
  await page.request.post(`${API}/api/auth/register`, { data: { email, password: 'P@ssword1' } });
  const lr = await page.request.post(`${API}/api/auth/login`, { data: { email, password: 'P@ssword1' } });
  const { data } = await lr.json();
  return data.token as string;
}

async function runOneHttp(page: any, token: string, url: string, method = 'GET', extra: Record<string, any> = {}) {
  await gotoApp(page, token);
  await addHttpNodeAndConnect(page, url, method, extra);
  await saveAndRun(page);
  return getTrace(page, token);
}

// ─── Account ───
test.describe('SF — Account', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Name: 'Acme Corp', Industry: 'Technology', Phone: '555-0100' } });
    const resp = lastOutput(steps);
    expect(resp?.body.success).toBe(true);
    expect(resp?.body.id).toBeTruthy();
  });

  test('Create or Update', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account/Upsert_Key__c/ACME-001`, 'PATCH',
      { sendBody: true, bodyContentType: 'json', body: { Name: 'Acme Corp Upserted', Industry: 'Healthcare' } });
    const resp = lastOutput(steps);
    expect(resp?.statusCode).toBe(200);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account/001AA000003TEST`);
    const resp = lastOutput(steps);
    expect(resp?.body.Name).toBe('Acme Corp');
    expect(resp?.body.Id).toBe('001AA000003TEST');
  });

  test('Get Many', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/query?q=SELECT+Id,Name+FROM+Account`);
    const resp = lastOutput(steps);
    expect(resp?.body.records).toBeDefined();
    expect(resp?.body.records.length).toBeGreaterThan(0);
  });

  test('Update', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account/001AA000003TEST`, 'PATCH',
      { sendBody: true, bodyContentType: 'json', body: { Phone: '555-9999' } });
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });

  test('Delete', async ({ page }) => {
    const token = await registerAndLogin(page);
    const cr = await page.request.post(`${STUB}/services/data/v63.0/sobjects/Account`, {
      data: { Name: 'To Delete Account' },
    });
    const { id: newId } = await cr.json();
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account/${newId || '001AA000003TEST'}`, 'DELETE');
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });

  test('Get Summary (describe)', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Account/describe`);
    const resp = lastOutput(steps);
    expect(resp?.body.describe.name).toBe('Account');
    expect(resp?.body.describe.fields).toBeDefined();
  });
});

// ─── Contact ───
test.describe('SF — Contact', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Contact`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { FirstName: 'Jane', LastName: 'Doe', Email: 'jane@example.com' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Contact/003AA000001TEST`);
    expect(lastOutput(steps)?.body.LastName).toBe('Doe');
  });

  test('Update', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Contact/003AA000001TEST`, 'PATCH',
      { sendBody: true, bodyContentType: 'json', body: { Phone: '555-1234' } });
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });

  test('Delete', async ({ page }) => {
    const token = await registerAndLogin(page);
    // Create via stub API directly, then delete via workflow
    const cr = await page.request.post(`${STUB}/services/data/v63.0/sobjects/Contact`, {
      data: { FirstName: 'Del', LastName: 'Contact', Email: 'del@example.com' },
    });
    const { id: newId } = await cr.json();
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Contact/${newId}`, 'DELETE');
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });
});

// ─── Lead ───
test.describe('SF — Lead', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Lead`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { LastName: 'Lovelace', Company: 'ACME', Email: 'ada@example.com' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Lead/00QAA000001TEST`);
    expect(lastOutput(steps)?.body.LastName).toBe('Lovelace');
  });

  test('Delete', async ({ page }) => {
    const token = await registerAndLogin(page);
    const cr = await page.request.post(`${STUB}/services/data/v63.0/sobjects/Lead`, {
      data: { LastName: 'Del Lead', Company: 'DelCo', Email: 'dlead@example.com' },
    });
    const { id: newId } = await cr.json();
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Lead/${newId}`, 'DELETE');
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });
});

// ─── Opportunity ───
test.describe('SF — Opportunity', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Opportunity`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Name: 'Big Deal', StageName: 'Prospecting', CloseDate: '2026-12-31' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Opportunity/006AA000001TEST`);
    expect(lastOutput(steps)?.body.Name).toBe('Big Deal');
  });

  test('Delete', async ({ page }) => {
    const token = await registerAndLogin(page);
    const cr = await page.request.post(`${STUB}/services/data/v63.0/sobjects/Opportunity`, {
      data: { Name: 'Del Opp', StageName: 'Prospecting', CloseDate: '2026-12-31' },
    });
    const { id: newId } = await cr.json();
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Opportunity/${newId}`, 'DELETE');
    expect(lastOutput(steps)?.statusCode).toBe(204);
  });
});

// ─── Case ───
test.describe('SF — Case', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Case`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Subject: 'Login Issue', Status: 'New', Origin: 'Email' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Case/500AA000001TEST`);
    expect(lastOutput(steps)?.body.Subject).toBe('Login Issue');
  });
});

// ─── Task ───
test.describe('SF — Task', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Task`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Subject: 'Follow up', Status: 'Not Started', Priority: 'Normal' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Task/00TAA000001TEST`);
    expect(lastOutput(steps)?.body.Subject).toBe('Follow up');
  });
});

// ─── ContentNote ───
test.describe('SF — ContentNote (Add Note)', () => {
  test('Create Note', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/ContentNote`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Title: 'Meeting Notes', Content: '<p>Discussed Q4 plan</p>' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });
});

// ─── Document ───
test.describe('SF — Document', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Document`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Name: 'Report.pdf', FolderId: '00lAA000001FOLD', Body: 'base64data' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Document/015AA000001TEST`);
    expect(lastOutput(steps)?.body.Name).toBe('Report.pdf');
  });
});

// ─── User ───
test.describe('SF — User', () => {
  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/User/005AA000001TEST`);
    expect(lastOutput(steps)?.body.Name).toBe('Test User');
  });

  test('Get Summary (describe)', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/User/describe`);
    const resp = lastOutput(steps);
    expect(resp?.body.describe.name).toBe('User');
  });
});

// ─── Flow ───
test.describe('SF — Flow', () => {
  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Flow/300AA000001TEST`);
    expect(lastOutput(steps)?.body.MasterLabel).toBe('My Flow');
  });
});

// ─── Attachment ───
test.describe('SF — Attachment', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Attachment`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { ParentId: '001AA000003TEST', Name: 'file.txt', Body: 'SGVsbG8=' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });
});

// ─── Search (SOSL) ───
test.describe('SF — Search', () => {
  test('Search (SOSL)', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/search?q=FIND+%7BAcme%7D+IN+ALL+FIELDS`);
    const resp = lastOutput(steps);
    expect(resp?.body.searchRecords).toBeDefined();
    expect(resp?.body.searchRecords.length).toBeGreaterThan(0);
  });
});

// ─── Custom Object ───
test.describe('SF — Custom Object', () => {
  test('Create', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Custom_Object__c`, 'POST',
      { sendBody: true, bodyContentType: 'json', body: { Name: 'Custom Record', Status__c: 'Active' } });
    expect(lastOutput(steps)?.body.success).toBe(true);
  });

  test('Get', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/sobjects/Custom_Object__c/a00AA000001TEST`);
    expect(lastOutput(steps)?.body.Name).toBe('Custom Record');
  });
});

// ─── Custom API Call ───
test.describe('SF — Custom API Call', () => {
  test('GET /custom/endpoint', async ({ page }) => {
    const token = await registerAndLogin(page);
    const steps = await runOneHttp(page, token, `${STUB}/services/data/v63.0/custom/endpoint`);
    expect(lastOutput(steps)?.body.success).toBe(true);
    expect(lastOutput(steps)?.body.endpoint).toBe('/services/data/v63.0/custom/endpoint');
  });
});
