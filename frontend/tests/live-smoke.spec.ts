import { test, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

// Opt-in, read-only integration smoke. No fixture responses and no model/search
// calls: this proves frontend/service wiring, not provider or learning quality.
test.describe('真实本地服务：只读前端联调', () => {
  test.skip(process.env.QA_LIVE_SMOKE !== '1', 'Set QA_LIVE_SMOKE=1 for the real local service smoke; offline E2E is separate.');
  for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
    test(`${viewport.name} 真实 capabilities、项目列表、入口和布局`, async ({ page }) => {
      const base = process.env.QA_LIVE_BASE_URL || 'http://127.0.0.1:8000';
      const reads: { path: string; status: number }[] = [];
      const mutations: string[] = [];
      const runtime: string[] = [];
      const consoleErrors: string[] = [];
      page.on('pageerror', error => runtime.push(error.message));
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      page.on('response', response => { const url = new URL(response.url()); if (url.pathname.startsWith('/api/')) reads.push({ path: url.pathname, status: response.status() }); });
      await page.route('**/api/**', route => {
        if (route.request().method() !== 'GET') { mutations.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`); return route.abort(); }
        return route.continue();
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      const capabilitiesResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/capabilities');
      const projectsResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/projects');
      await page.goto(base);
      expect((await capabilitiesResponse).status()).toBe(200);
      expect((await projectsResponse).status()).toBe(200);
      await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
      await expect(page.getByLabel('项目名称', { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '分析项目' })).toBeVisible();
      await expect(page.locator('vite-error-overlay')).toHaveCount(0);
      await page.getByRole('button', { name: '我的项目' }).click();
      await expect(page.getByLabel('已保存项目')).toBeVisible();
      await page.getByRole('button', { name: '我的项目' }).click();
      const layout = await page.evaluate(() => {
        const heading = document.querySelector('h1')!;
        const lines = [...heading.childNodes].filter(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()).flatMap(node => {
          const range = document.createRange(); range.selectNodeContents(node); return [...range.getClientRects()].map(rect => ({ top: rect.top, width: rect.width }));
        });
        return { viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth, headingLines: lines.length, heading: heading.textContent };
      });
      expect(layout.scrollWidth).toBeLessThanOrEqual(layout.viewport);
      expect(layout.headingLines).toBe(2);
      expect(mutations).toEqual([]); expect(runtime).toEqual([]); expect(consoleErrors).toEqual([]);
      const folder = resolve(process.env.QA_LIVE_OUTPUT_DIR || resolve(process.cwd(), '../evidence/browser/live'));
      await mkdir(folder, { recursive: true });
      await page.screenshot({ path: resolve(folder, `${viewport.name}-entry.png`), fullPage: false, animations: 'disabled' });
      await writeFile(resolve(folder, `${viewport.name}-observations.json`), JSON.stringify({ kind: 'real local service read-only smoke', base, viewport, reads, mutations, runtime, consoleErrors, layout }, null, 2));
    });
  }
});
