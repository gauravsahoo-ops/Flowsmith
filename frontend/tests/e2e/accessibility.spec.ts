import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const API = process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8000';

async function seedSession(page: any) {
  const email = `a11y_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
  const password = 'P@ssword1';
  const reg = await page.request.post(`${API}/api/auth/register`, {
    data: { email, password },
  });
  if (!reg.ok()) throw new Error(`register failed ${reg.status()}: ${await reg.text()}`);
  const login = await page.request.post(`${API}/api/auth/login`, {
    data: { email, password },
  });
  const payload = await login.json();
  if (!login.ok() || !payload?.data?.token) {
    throw new Error(`login failed ${login.status()}: ${JSON.stringify(payload)}`);
  }
  await page.addInitScript(
    ({ token, user }: { token: string; user: unknown }) => {
      localStorage.setItem('mat_token', token);
      localStorage.setItem('flowsmith_user', JSON.stringify(user));
    },
    { token: payload.data.token, user: payload.data.user },
  );
}

function summarize(violations: any[]) {
  return violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes?.slice(0, 5).map((n: any) => n.target),
  }));
}

test.describe('Accessibility audit', () => {
  test('login page has no critical or serious axe violations', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle').catch(() => {});
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const blocking = results.violations.filter((v) =>
      ['critical', 'serious'].includes(v.impact || ''),
    );
    console.log('LOGIN_A11Y', JSON.stringify(summarize(blocking), null, 2));
    expect(blocking, JSON.stringify(summarize(blocking), null, 2)).toEqual([]);
  });

  test('keyboard focus remains visible on the login form', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.keyboard.press('Tab');
    const focus = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return null;
      const style = getComputedStyle(el);
      return {
        tag: el.tagName,
        label: el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.textContent?.slice(0, 40),
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        boxShadow: style.boxShadow,
      };
    });
    expect(focus).not.toBeNull();
    expect(focus!.tag).not.toBe('BODY');
    const hasVisibleIndicator =
      (focus!.outlineStyle !== 'none' && focus!.outlineWidth !== '0px') ||
      (focus!.boxShadow && focus!.boxShadow !== 'none');
    expect(hasVisibleIndicator, JSON.stringify(focus)).toBeTruthy();
  });

  test('authenticated surfaces have no critical or serious axe violations', async ({ page }) => {
    test.setTimeout(120000);
    await seedSession(page);

    const surfaces = [
      ['overview', '/overview'],
      ['workflows', '/workflows'],
      ['integrations', '/integrations'],
      ['ai', '/ai'],
      ['executions', '/executions'],
      ['approvals', '/approvals'],
      ['credentials', '/credentials'],
      ['monitoring', '/monitoring'],
      ['help', '/help'],
    ] as const;

    const failures: Record<string, unknown> = {};
    for (const [label, path] of surfaces) {
      await page.goto(path);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(400);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      const blocking = results.violations.filter((v) =>
        ['critical', 'serious'].includes(v.impact || ''),
      );
      if (blocking.length) failures[label] = summarize(blocking);
    }

    console.log('AUTH_A11Y', JSON.stringify(failures, null, 2));
    expect(failures, JSON.stringify(failures, null, 2)).toEqual({});
  });

  test('authenticated surfaces have a keyboard tab order', async ({ page }) => {
    test.setTimeout(120000);
    await seedSession(page);

    const surfaces = [
      ['overview', '/overview'],
      ['workflows', '/workflows'],
      ['integrations', '/integrations'],
      ['ai', '/ai'],
      ['executions', '/executions'],
      ['approvals', '/approvals'],
      ['credentials', '/credentials'],
      ['monitoring', '/monitoring'],
      ['help', '/help'],
    ] as const;

    const failures: Record<string, unknown> = {};
    for (const [label, path] of surfaces) {
      await page.goto(path);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(300);
      const order: Array<{ tag: string; name: string; visible: boolean }> = [];
      for (let i = 0; i < 8; i += 1) {
        await page.keyboard.press('Tab');
        const info = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el) return null;
          const style = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return {
            tag: el.tagName,
            name: (
              el.getAttribute('aria-label') ||
              el.getAttribute('placeholder') ||
              el.textContent ||
              ''
            )
              .trim()
              .slice(0, 50),
            visible:
              rect.width > 0 &&
              rect.height > 0 &&
              style.visibility !== 'hidden' &&
              style.display !== 'none',
          };
        });
        if (info) order.push(info);
      }
      const distinct = new Set(order.map((item) => `${item.tag}:${item.name}`));
      const firstThree = order.slice(0, 3);
      if (distinct.size < 3 || firstThree.some((item) => item.tag === 'BODY')) {
        failures[label] = order;
      }
    }

    console.log('TAB_ORDER', JSON.stringify(failures, null, 2));
    expect(failures, JSON.stringify(failures, null, 2)).toEqual({});
  });

  test('OpenAPI import modal traps keyboard focus and closes with Escape', async ({ page }) => {
    await seedSession(page);
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle').catch(() => {});
    const importBtn = page.getByRole('button', { name: /Import OpenAPI/i });
    await expect(importBtn).toBeVisible();
    await importBtn.click();
    const modal = page.locator('.oai-modal-window');
    await expect(modal).toBeVisible();

    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Tab');
      const focusInside = await page.evaluate(() => {
        const dialog = document.querySelector('.oai-modal-window');
        return Boolean(
          dialog && document.activeElement && dialog.contains(document.activeElement),
        );
      });
      expect(focusInside, `focus escaped the modal after ${i + 1} Tab presses`).toBeTruthy();
    }

    await page.keyboard.press('Escape');
    await expect(modal).not.toBeVisible();
  });
});
