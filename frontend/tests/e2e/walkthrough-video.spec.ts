import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test.use({
  video: { mode: 'on', size: { width: 1280, height: 720 } },
  viewport: { width: 1280, height: 720 },
});

const API = 'http://127.0.0.1:8000';

test('product walkthrough video', async ({ page }) => {
  test.setTimeout(120000);
  const email = `walkthrough_${Date.now()}@example.com`;
  const password = 'P@ssword1';

  await page.request.post(`${API}/api/auth/register`, { data: { email, password } });
  const login = await page.request.post(`${API}/api/auth/login`, { data: { email, password } });
  const payload = await login.json();
  expect(login.ok()).toBeTruthy();

  await page.addInitScript(
    ({ token, user }: { token: string; user: unknown }) => {
      localStorage.setItem('mat_token', token);
      localStorage.setItem('flowsmith_user', JSON.stringify(user));
    },
    { token: payload.data.token, user: payload.data.user },
  );

  await page.goto('/');
  await page.waitForTimeout(1200);

  const surfaces = [
    '/overview',
    '/workflows',
    '/integrations',
    '/ai',
    '/executions',
    '/approvals',
    '/credentials',
    '/monitoring',
    '/help',
  ];
  for (const path of surfaces) {
    await page.goto(path);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(900);
  }

  const workflow = await page.request.post(`${API}/api/workflows`, {
    headers: { Authorization: `Bearer ${payload.data.token}` },
    data: {
      id: `wf_walkthrough_${Date.now()}`,
      name: 'Walkthrough Workflow',
      nodes: [
        { id: 'trigger', type: 'manual_trigger', position: { x: 80, y: 140 } },
        { id: 'set', type: 'set_data', position: { x: 360, y: 140 }, parameters: { fields: { hello: 'world' } } },
      ],
      connections: [{ source: 'trigger', target: 'set' }],
      settings: {},
    },
  });
  const wf = (await workflow.json()).data;
  if (workflow.ok() && wf?.id) {
    await page.goto(`/workflows/${wf.id}`);
    await page.waitForSelector('.canvas', { state: 'attached', timeout: 30000 });
    await page.waitForTimeout(1600);
    await page.evaluate(() => window.__uiStore?.getState()?.openNodeEditor('set'));
    await page.waitForTimeout(1600);
  }

  const video = page.video();
  if (video) {
    const out = resolve('..', 'docs', 'media', 'flowsmith-walkthrough.webm');
    mkdirSync(resolve('..', 'docs', 'media'), { recursive: true });
    await page.close();
    await video.saveAs(out);
  }
});
