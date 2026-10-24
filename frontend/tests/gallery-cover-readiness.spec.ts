import { expect, test } from '@playwright/test';

// All responses and images below are synthetic isolated UI controls, not
// evidence about the availability or teaching quality of real videos.
const input = { name: '封面准备测试', requirements: '隔离展示验证', student_level: 'any', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili'] };
const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#3157ff"/></svg>';
function view(image: string | null, status: string = 'pending') {
  return { project_id: 'cover-ready', current_version: 1, input, versions: [], snapshot_revision: `${image}:${status}`,
    version: { version: 1, status: 'completed', input, analysis: { scope: '', technical_plan: '', assumptions: [], analysis_format: 'concept_list_v1', knowledge_points: [{ id: 'k1', name: '循环', description: '', selection: 'learn' }] }, confirmation: { confirmed_at: '2026-10-24T00:00:00Z' }, batches: [], created_at: '2026-10-24T00:00:00Z' },
    pipeline: { terminal: true, catalog_pending: true }, points: [{ project_knowledge_point_id: 'k1', name: '循环', status: 'completed', selection: 'learn', result: { knowledge_point_id: 'k1', recommendation_policy: 'helpful-video-v1', video_recommendations: [{ resource: { resource_id: 'v1', title: '循环视频', url: 'https://www.bilibili.com/video/BV1234567890', platform: 'bilibili', thumbnail_url: image, cover_status: status }, matched_chapters: [] }] } }] };
}

test('title waits through metadata backfill, image failures and timeouts remain usable, later URLs recover', async ({ page }, testInfo) => {
  let current = view('https://covers.example.org/slow.svg', 'ready');
  let releaseImage!: () => void;
  const waitImage = new Promise<void>(resolve => { releaseImage = resolve; });
  let releaseTimedOutImage!: () => void;
  const waitTimedOutImage = new Promise<void>(resolve => { releaseTimedOutImage = resolve; });
  const writes: string[] = [], errors: string[] = [], images: string[] = [];
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.clock.install();
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    class ControlledStream extends EventTarget {
      listener = (event: Event) => this.dispatchEvent(new MessageEvent('snapshot', { data: JSON.stringify((event as CustomEvent).detail) }));
      constructor() { super(); window.addEventListener('__cover-snapshot', this.listener); }
      close() { window.removeEventListener('__cover-snapshot', this.listener); }
    }
    window.EventSource = ControlledStream as unknown as typeof EventSource;
  });
  const update = async (snapshot: ReturnType<typeof view>) => page.evaluate(value => window.dispatchEvent(new CustomEvent('__cover-snapshot', { detail: value })), snapshot);
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') { writes.push(route.request().url()); return route.abort(); }
    const url = new URL(route.request().url());
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: { teaching_match_enabled: false, platforms: [], limits: {} } });
    if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
    return route.fulfill({ json: current });
  });
  await page.route('https://covers.example.org/**', async route => {
    images.push(route.request().url());
    if (route.request().url().endsWith('slow.svg')) await waitImage;
    if (route.request().url().endsWith('timeout.svg')) await waitTimedOutImage;
    if (route.request().url().endsWith('broken.svg')) return route.fulfill({ status: 204, body: '' });
    await route.fulfill({ contentType: 'image/svg+xml', body: svg });
  });
  await page.goto('/?project=cover-ready&version=1');
  const card = page.locator('[data-resource-id="v1"]');
  await expect(card).toHaveAttribute('aria-busy', 'true');
  await expect(card.locator('img')).toHaveAttribute('loading', 'eager');
  await expect(card.locator('.video-card-content')).toHaveCSS('opacity', '0');
  expect(images).toContain('https://covers.example.org/slow.svg');
  await expect(page.locator('html')).not.toHaveAttribute('data-motion-kind');
  await page.screenshot({ path: testInfo.outputPath('cover-waiting.png') });
  releaseImage();
  await expect(card).not.toHaveAttribute('aria-busy');
  await expect(card.locator('.video-card-content')).toHaveCSS('opacity', '1');
  await expect(card.getByRole('heading')).toHaveText('循环视频');
  await card.evaluate(element => { element.setAttribute('data-test-instance', 'original'); });
  await page.screenshot({ path: testInfo.outputPath('cover-ready.png') });

  await update(view('https://covers.example.org/broken.svg', 'ready'));
  await expect.poll(() => images.includes('https://covers.example.org/broken.svg')).toBe(true);
  await expect(card).not.toHaveAttribute('aria-busy');
  await expect(card.locator('.video-cover-title a')).toBeVisible();
  await expect(card.locator('.cover-placeholder')).toBeVisible();

  await update(view(null, 'pending'));
  await expect(card).toHaveAttribute('aria-busy', 'true');
  // Metadata backfill has no browser image request to time out. Keep the whole
  // card hidden beyond the old six-second cutoff until the backend resolves it.
  await page.clock.fastForward(6500);
  await expect(card).toHaveAttribute('aria-busy', 'true');
  await expect(card.locator('.video-card-content')).toHaveCSS('opacity', '0');
  await expect(card.locator('.video-card-content')).toHaveAttribute('inert', '');
  await expect(card.locator('.video-card-content')).toHaveAttribute('aria-hidden', 'true');
  await expect(card.locator('.video-card-skeleton')).toBeVisible();

  await update(view('https://covers.example.org/recovered.svg', 'ready'));
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 640);
  await expect(card).not.toHaveAttribute('aria-busy');
  await expect(card.locator('.video-card-content')).toHaveCSS('opacity', '1');

  await update(view(null, 'pending'));
  await expect(card).toHaveAttribute('aria-busy', 'true');
  await update(view(null, 'failed'));
  await expect(card).not.toHaveAttribute('aria-busy');
  await expect(card.locator('.video-cover-title a')).toBeVisible();
  await expect(card.locator('.cover-placeholder')).toBeVisible();

  await update(view('https://covers.example.org/timeout.svg', 'ready'));
  await expect(card).toHaveAttribute('aria-busy', 'true');
  await page.clock.fastForward(6500);
  await expect(card).not.toHaveAttribute('aria-busy');
  await expect(card.locator('.video-card-content')).toHaveCSS('opacity', '1');
  releaseTimedOutImage();
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 640);
  await expect(card).toHaveAttribute('data-test-instance', 'original');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});
