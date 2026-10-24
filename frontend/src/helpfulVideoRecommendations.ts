import { courseImageUrl, externalUrl } from './safeUrls.ts';
import type { HelpfulVideoChapter, HelpfulVideoRecommendation, ResultGroup } from './types';

export function hasHelpfulVideoPolicy(group: ResultGroup): boolean {
  return group.recommendation_policy === 'helpful-video-v1';
}

export type HelpfulGalleryVideo = {
  id: string; title: string; image?: string | null; href: string; urlKey: string;
  source: 'helpful-video'; knowledgePointIds: string[]; recommendedAt?: string;
  chapters: HelpfulGalleryChapter[];
};
export type HelpfulGalleryChapter = Pick<HelpfulVideoChapter, 'chapter_id' | 'title' | 'index'> & { href?: string };
type VisibleHelpfulVideo = HelpfulVideoRecommendation & { href: string; urlKey: string };

function urlKey(href: string): string {
  const url = new URL(href);
  url.hash = '';
  // Each Bilibili video stays one card; observed part links live in its title.
  for (const key of [...url.searchParams.keys()]) {
    if (key.startsWith('utm_') || ['spm_id_from', 'share_source', 'share_medium', 'vd_source'].includes(key)) url.searchParams.delete(key);
  }
  url.pathname = url.pathname.replace(/\/+$/, '') || '/';
  if (['bilibili.com', 'www.bilibili.com'].includes(url.hostname) && /^\/video\/(?:BV[0-9A-Za-z]+|av\d+)$/i.test(url.pathname)) {
    url.hostname = 'www.bilibili.com';
    url.searchParams.delete('p');
  }
  if (['icourse163.org', 'www.icourse163.org'].includes(url.hostname)) {
    const slug = /^\/course\/(?:[A-Za-z0-9_][A-Za-z0-9_-]{0,127})?-([0-9]{1,20})$/.exec(url.pathname);
    const keys = [...url.searchParams.keys()];
    const valid = new Set(keys).size === keys.length && keys.every(key => ['cid', 'tid', 'outVendor'].includes(key)) &&
      [...url.searchParams].every(([key, value]) => (key === 'outVendor' ? /^[A-Za-z0-9_-]{1,128}$/ : /^[0-9]{1,20}$/).test(value));
    const courseId = valid && (slug && !keys.includes('cid') ? slug[1] : url.pathname === '/course/detail.htm' ? url.searchParams.get('cid') : null);
    if (courseId) return `icourse163:${courseId}:${url.searchParams.get('tid') || ''}`;
  }
  url.searchParams.sort();
  return url.href;
}

/** The server has judged helpfulness. Page, catalog and playback checks must
 * not become a second admission gate for this explicitly selected policy. */
export function helpfulVideoRecommendations(group: ResultGroup, platform = 'all'): VisibleHelpfulVideo[] {
  if (!hasHelpfulVideoPolicy(group)) return [];
  const rows: VisibleHelpfulVideo[] = [];
  for (const entry of group.video_recommendations || []) {
    const resource = entry?.resource;
    if (!resource || resource.requires_payment === true ||
        typeof resource.resource_id !== 'string' || !resource.resource_id.trim() ||
        typeof resource.title !== 'string' || !resource.title.trim() ||
        platform !== 'all' && resource.platform !== platform) continue;
    const href = externalUrl(resource.url);
    if (!href) continue;
    rows.push({ ...entry, href, urlKey: urlKey(href) });
  }
  return rows;
}

function chinesePriority(row: VisibleHelpfulVideo): number {
  return /^zh(?:[-_]|$)/i.test(row.resource.language || '') || /[\u3400-\u9fff]/.test(row.resource.title) ? 0 : 1;
}

function chaptersFor(row: VisibleHelpfulVideo): HelpfulGalleryChapter[] {
  const chapters = new Map<string, HelpfulGalleryChapter>();
  const videoTitle = row.resource.title.replace(/\s+/g, '').normalize('NFKC');
  for (const chapter of row.matched_chapters || []) {
    if (!chapter?.chapter_id || typeof chapter.title !== 'string' || !chapter.title.trim()) continue;
    // A single-part catalog often repeats the video title verbatim.
    if (chapter.title.replace(/\s+/g, '').normalize('NFKC') === videoTitle) continue;
    const href = chapter.url ? externalUrl(chapter.url) : undefined;
    chapters.set(chapter.chapter_id, { chapter_id: chapter.chapter_id, title: chapter.title, index: chapter.index, href });
  }
  return [...chapters.values()];
}

/** Dedupe in the current view only: the same URL retains every selected point
 * association, and remains visible when either point is selected separately. */
export function helpfulVideoCovers(groups: { pointId: string; result: ResultGroup }[], platform = 'all'): Map<string, HelpfulGalleryVideo> {
  const covers = new Map<string, HelpfulGalleryVideo>();
  const entries = groups.flatMap(({ pointId, result }) => helpfulVideoRecommendations(result, platform).map(row => ({ pointId, row })));
  entries.sort((a, b) => chinesePriority(a.row) - chinesePriority(b.row) || (b.row.score || 0) - (a.row.score || 0));
  for (const { pointId, row } of entries) {
    const existing = covers.get(row.urlKey);
    const stamp = typeof row.added_at === 'string' && Number.isFinite(Date.parse(row.added_at)) ? row.added_at : undefined;
    if (existing) {
      // One course may arrive through several points before its native cover.
      // Preserve the ranked card while filling metadata from a later alias.
      existing.image ||= courseImageUrl(row.resource.thumbnail_url);
      if (!existing.knowledgePointIds.includes(pointId)) existing.knowledgePointIds.push(pointId);
      if (stamp && (!existing.recommendedAt || Date.parse(stamp) < Date.parse(existing.recommendedAt))) existing.recommendedAt = stamp;
      const chapters = new Map(existing.chapters.map(chapter => [chapter.chapter_id, chapter]));
      for (const chapter of chaptersFor(row)) chapters.set(chapter.chapter_id, chapter);
      existing.chapters = [...chapters.values()].sort((a, b) => a.index - b.index);
    } else {
      covers.set(row.urlKey, {
        id: row.resource.resource_id, title: row.resource.title, image: courseImageUrl(row.resource.thumbnail_url),
        href: row.href, urlKey: row.urlKey, source: 'helpful-video', knowledgePointIds: [pointId], recommendedAt: stamp,
        chapters: chaptersFor(row).sort((a, b) => a.index - b.index),
      });
    }
  }
  return covers;
}
