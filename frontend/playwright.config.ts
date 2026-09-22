import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..');
const venvPython = join(root, '.venv', 'Scripts', 'python.exe');
const backendPython = existsSync(venvPython) ? venvPython : 'python';

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/*.spec.ts',
  testIgnore: ['**/node_modules/**', '**/src/**', '**/*.test.js', '**/*.test.ts', '**/workflowStore.test.js', '**/src/stores/**'],
  timeout: 60000,
  retries: 2,
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: `"${backendPython}" -m app.serve`,
      cwd: join(root, 'backend'),
      url: 'http://127.0.0.1:8000/api/health',
      // The backend must be started by Playwright so it picks up the
      // dev/E2E SSRF escape hatch pointing at the local Salesforce stub
      // (a pre-existing server without these vars would reject the
      // stub's 127.0.0.1:8181 with confusing "SSRF policy" errors).
      reuseExistingServer: true,
      env: {
        SAFE_HTTP_ALLOWED_HOSTS: '127.0.0.1',
        SAFE_HTTP_ALLOWED_PORTS: '8181',
      },
      timeout: 120000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 120000,
    },
    {
      command: 'node tests/e2e/stub-server.mjs',
      url: 'http://127.0.0.1:8181/health',
      reuseExistingServer: true,
      timeout: 30000,
    },
    {
      command: 'node tests/e2e/enterprise-stub-server.mjs',
      url: 'http://127.0.0.1:8182/api/health',
      reuseExistingServer: true,
      timeout: 30000,
    },
  ],
  reporter: [['html', { open: 'never' }], ['list']],
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});