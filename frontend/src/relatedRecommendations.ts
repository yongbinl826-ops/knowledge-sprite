import { externalUrl } from './safeUrls.ts';
import type { RelatedRecommendation, Resource, ResultGroup } from './types';
import { hasVerifiedReferencePage, isVerifiedVideoPage, type VideoPageFacts } from './verifiedVideoPage.ts';

export type VisibleReference = RelatedRecommendation & { href: string; urlKey: string; accessibleReason: string };
export function hasRelatedRecommendationPolicy(group: ResultGroup): boolean {
  // Unknown future policies also prevent a fallback to unfiltered discovery.
  return !!group.recommendation_policy || group.related_recommendations !== undefined || group.related_platform_recommendations !== undefined;
}
export function recommendationUrlKey(resource: { url: string; canonical_url?: string | null }): string | undefined {
  const href = externalUrl(resource.url);
  if (!href) return;
  return (resource.canonical_url ? externalUrl(resource.canonical_url) : undefined) || href;
}
function bilibiliPart(value: unknown): { href: string; video: string; part?: number } | undefined {
  if (typeof value !== 'string') return;
  const href = externalUrl(value);
  if (!href) return;
  const url = new URL(href), match = /^\/video\/(BV[0-9A-Za-z]{10})\/?$/.exec(url.pathname);
  if (url.protocol !== 'https:' || !['bilibili.com', 'www.bilibili.com'].includes(url.hostname) ||
      url.port || url.hash || !match || url.search && !/^\?p=[1-9][0-9]{0,5}$/.test(url.search)) return;
  return { href, video: match[1], part: url.search ? Number(url.searchParams.get('p')) : undefined };
}
/** Select only a cited, individually observed chapter. An aggregate catalog or
 * model/search text cannot identify which part teaches the current point. */
function observedSourceKey(value: unknown): string | undefined {
  const page = bilibiliPart(value);
  if (!page) return;
  // A page with ?p= is a retrieval source, not automatically the matched lesson.
  // Match only the explicitly declared raw/canonical source; do not borrow from
  // an arbitrary other part of the same BV.
  const url = new URL(page.href);
  return `${url.origin}/video/${page.video}${page.part ? `?p=${page.part}` : ''}`;
}
function referenceTargetUrl(row: RelatedRecommendation, fallback: string): string {
  const resource = bilibiliPart(fallback);
  if (!resource || !isVerifiedVideoPage(row.resource) ||
      !row.reference.basis.includes('catalog')) return fallback;
  const canonical = bilibiliPart(row.resource.canonical_url || fallback);
  if (!canonical || canonical.video !== resource.video ||
      !resource.part && canonical.part ||
      resource.part && canonical.part && resource.part !== canonical.part) return fallback;
  // Page-based support can establish an already specific target. This narrow
  // change only replaces an incidental discovery part on catalog-only references.
  if (resource.part && row.reference.basis.some(kind => kind !== 'catalog')) return fallback;
  const sourceUrls = new Set([observedSourceKey(resource.href), observedSourceKey(canonical.href)]);
  const cited = new Set(row.reference.evidence_ids);
  const chapters: { href: string; part: number }[] = [];
  for (const evidence of row.evidence) {
    if (!cited.has(evidence.evidence_id) || evidence.kind !== 'catalog' || evidence.cache?.stale === true ||
        typeof evidence.source !== 'string' || !evidence.source.trim() ||
        !/^chapters\.\d+$/.test(evidence.field || '') || typeof evidence.text !== 'string' || evidence.text.length > 16_384 ||
        !sourceUrls.has(observedSourceKey(evidence.url))) continue;
    try {
      const chapter: unknown = JSON.parse(evidence.text);
      if (!chapter || typeof chapter !== 'object' || Array.isArray(chapter)) continue;
      const entry = chapter as { url?: unknown; title?: unknown; source_url?: unknown; page_number?: unknown; requires_payment?: unknown };
      const target = bilibiliPart(entry.url);
      if (!target?.part || target.video !== resource.video || typeof entry.title !== 'string' || !entry.title.trim() ||
          entry.requires_payment === true || entry.page_number !== undefined && entry.page_number !== target.part ||
          !sourceUrls.has(observedSourceKey(entry.source_url))) continue;
      chapters.push({ href: target.href, part: target.part });
    } catch { /* Keep the original link when catalog evidence is malformed. */ }
  }
  // An original explicit part that is itself a cited matching lesson is exact;
  // retain it even when another matching chapter has a lower part number.
  if (resource.part && chapters.some(chapter => chapter.part === resource.part)) return fallback;
  return chapters.sort((a, b) => a.part - b.part)[0]?.href || fallback;
}
/** A primary card may reuse its own point's independently cited chapter target.
 * Its title/status and any already explicit part remain authoritative. */
export function verifiedReferenceChapterTarget(resource: Pick<Resource, 'url' | 'canonical_url'> & VideoPageFacts,
                                               row: VisibleReference, pointId: string): string | undefined {
  if (row.reference.knowledge_point_id !== pointId || !isVerifiedVideoPage(resource) || !hasVerifiedReferencePage(row)) return;
  const href = externalUrl(resource.url);
  if (!href) return;
  const original = new URL(href);
  if (original.searchParams.has('p')) return;
  // Tracking parameters do not choose a part. The independently checked
  // canonical root still has to identify the same BV as the original URL.
  original.search = '';
  const video = bilibiliPart(original.href), canonical = bilibiliPart(resource.canonical_url || original.href);
  const parent = bilibiliPart(row.resource.canonical_url || row.resource.url);
  if (!video || !canonical || canonical.part || canonical.video !== video.video ||
      !parent || parent.part || parent.video !== video.video) return;
  const target = bilibiliPart(referenceTargetUrl(row, parent.href));
  const originalReference = bilibiliPart(row.resource.url);
  if (originalReference?.part && originalReference.part !== target?.part) return;
  if (target?.part && target.video === video.video && target.href === row.href) return target.href;
}
function visibleReference(row: RelatedRecommendation, pointId: string): VisibleReference | undefined {
  const { reference, resource, evidence } = row || {};
  if (!resource || !reference || reference.policy !== 'related-reference-v1' || reference.kind !== 'related_reference' ||
      reference.knowledge_point_id !== pointId || reference.exact_teaching_verified !== false ||
      !Number.isFinite(reference.ranking_score) || typeof reference.reason !== 'string' || !reference.reason.trim() ||
      !['observed', 'parent_course', 'unconfirmed'].includes(reference.technical_context) ||
      !Array.isArray(reference.basis) || !reference.basis.length || reference.basis.some(value => typeof value !== 'string' || !value.trim()) ||
      !Array.isArray(reference.evidence_ids) || !reference.evidence_ids.length || !Array.isArray(evidence) ||
      evidence.some(item => !item || typeof item.evidence_id !== 'string') ||
      typeof resource.resource_id !== 'string' || !resource.resource_id || typeof resource.title !== 'string' || !resource.title.trim() ||
      typeof resource.resource_type !== 'string') return;
  const ids = new Map(evidence.map(item => [item.evidence_id, item]));
  if (ids.size !== evidence.length || new Set(reference.evidence_ids).size !== reference.evidence_ids.length ||
      reference.evidence_ids.some(id => typeof id !== 'string' || !id || !ids.has(id) ||
        ((ids.get(id) as { resource_id?: string })?.resource_id !== undefined && (ids.get(id) as { resource_id?: string }).resource_id !== resource.resource_id))) return;
  const href = externalUrl(resource.url), urlKey = recommendationUrlKey(resource);
  if (!href || !urlKey) return;
  return { ...row, href: referenceTargetUrl(row, href), urlKey, accessibleReason: `相关参考，精确讲授未验证。${reference.reason}${resource.access_notice ? ` ${resource.access_notice}` : ''}` };
}
/** Relevance is a server policy, not proof of teaching. Search and parent context
 * remain references and never become strict match/skill coverage records. */
export function relatedRecommendations(group: ResultGroup, platform = 'all', excludedUrls: ReadonlySet<string> = new Set()): VisibleReference[] {
  const rows = platform === 'all' ? group.related_recommendations || []
    : group.related_platform_recommendations?.[platform] ?? (group.related_recommendations || []).filter(row => row.resource.platform === platform);
  const unique = new Map<string, VisibleReference>();
  for (const row of rows) {
    const checked = visibleReference(row, group.knowledge_point_id);
    if (!checked || excludedUrls.has(checked.urlKey) || platform !== 'all' && checked.resource.platform !== platform) continue;
    const previous = unique.get(checked.urlKey);
    if (!previous || checked.reference.ranking_score > previous.reference.ranking_score) unique.set(checked.urlKey, checked);
  }
  return [...unique.values()].sort((a, b) => b.reference.ranking_score - a.reference.ranking_score);
}
