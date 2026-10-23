import { expect, type Page } from '@playwright/test';

/** Each displayed resource has a cover and its title, with no restored reason
 * panels. The source toolbar is separate from the resource content. */
export async function expectGalleryTitlesOnly(page: Page, expectedTitles?: string[]) {
  const pane = page.locator('.stage-content');
  const cards = pane.locator('.video-cover-card');
  const titles = pane.locator('.video-cover-title a');
  await expect(titles).toHaveCount(await cards.count());
  if (expectedTitles) await expect(titles).toHaveText(expectedTitles);
  for (const card of await cards.all()) {
    const cover = card.locator('a.course-cover'), title = card.locator('.video-cover-title a');
    await expect(title).toBeVisible();
    const name = (await title.innerText()).trim(); expect(name.length).toBeGreaterThan(0);
    await expect(title).toHaveAccessibleName(name);
    const href = await cover.getAttribute('href');
    await expect(title).toHaveAttribute('href', href!);
    expect(await cover.getAttribute('aria-label')).toContain(name);
    for (const link of await card.getByRole('link').all()) {
      const url = new URL((await link.getAttribute('href'))!);
      expect(['https:', 'http:']).toContain(url.protocol);
      expect(url.username + url.password).toBe('');
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
  }
  const normalize = (value: string) => value.replace(/\s+/g, ' ').trim();
  expect(normalize(await pane.locator('.gallery-motion').innerText())).toBe(normalize((await titles.allInnerTexts()).join(' ')));
  await expect(pane.locator('.gallery-toolbar').getByRole('combobox', { name: '视频来源' })).toBeVisible();
  await expect(pane.locator('select')).toHaveCount(1);
  await expect(pane.locator('h1,h2:not(.video-cover-title),h3,h4,p,blockquote,.course-info,.recommendation-reason')).toHaveCount(0);
}
