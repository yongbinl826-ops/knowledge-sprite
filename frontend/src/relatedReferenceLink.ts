import { externalUrl } from './safeUrls.ts';
import type { RelatedRecommendation } from './types';
import { hasVerifiedReferencePage } from './verifiedVideoPage.ts';

const failed = new Set(['unsafe_url', 'not_found', 'error_page', 'unavailable', 'removed', 'deleted', 'access_denied', 'access_blocked', 'robots_blocked']);
const tracking = new Set(['fbclid', 'gclid', 'dclid', 'msclkid', 'igshid', 'spm_id_from', 'vd_source', 'from_spmid', 'spmid', 'share_source', 'share_medium', 'share_plat', 'share_session_id', 'share_tag', 'mc_cid', 'mc_eid']);

/** Compare observed native entries only. This key is never used for navigation. */
function nativeEntry(value: unknown): { key: string; type: 'video' | 'course' } | undefined {
  if (typeof value !== 'string' || /[\x00-\x20\x7f\\]/.test(value)) return;
  const safe = externalUrl(value);
  if (!safe) return;
  const url = new URL(safe), host = url.hostname;
  if (url.port || url.hash) return;
  const bili = ['www.bilibili.com', 'bilibili.com'].includes(host);
  for (const key of [...url.searchParams.keys()]) {
    if (tracking.has(key.toLowerCase()) || key.toLowerCase().startsWith('utm_') || bili && key.toLowerCase() === 'uid') url.searchParams.delete(key);
  }
  let type: 'video' | 'course';
  if (bili && /^\/(?:zh-Hans\/)?video\/(?:BV[0-9A-Za-z]{10}|av\d+)\/?$/.test(url.pathname)) {
    if (url.search && !/^\?p=[1-9][0-9]{0,5}$/.test(url.search)) return;
    // Do not let URLSearchParams turn an encoded p key into observed native syntax.
    if (url.search && !new URL(safe).search.slice(1).split('&').includes(url.search.slice(1))) return;
    url.pathname = url.pathname.replace(/^\/zh-Hans\//, '/');
    type = 'video';
  } else if (['www.icourse163.org', 'icourse163.org'].includes(host) && /^\/(?:course|learn)\/(?:[A-Za-z0-9_-]*-)?\d+\/?$/.test(url.pathname)) {
    type = 'course';
  } else if (['www.xuetangx.com', 'xuetangx.com'].includes(host) && /^\/course\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)) {
    type = 'course';
  } else if (['www.youtube.com', 'youtube.com', 'm.youtube.com'].includes(host) && url.pathname === '/watch' &&
      url.searchParams.getAll('v').length === 1 && /^[A-Za-z0-9_-]{11}$/.test(url.searchParams.get('v') || '')) {
    type = 'video';
  } else if (['youtu.be', 'www.youtu.be'].includes(host) && /^\/[A-Za-z0-9_-]{11}\/?$/.test(url.pathname)) {
    type = 'video';
  } else return;
  url.pathname = url.pathname.replace(/\/$/, '');
  return { key: url.href, type };
}

/** A projected chapter is bound by the cited catalog's observed JSON target
 * and its own parent source. Same BV alone never supplies a chapter link. */
function catalogParentKey(evidence: RelatedRecommendation['evidence'][number], targetKey: string): string | undefined {
  if (evidence.kind !== 'catalog' || !/^chapters\.\d+$/.test(evidence.field || '') ||
      typeof evidence.text !== 'string' || evidence.text.length > 16_384) return;
  try {
    const entry = JSON.parse(evidence.text);
    if (!entry || typeof entry !== 'object' || Array.isArray(entry) ||
        typeof entry.title !== 'string' || !entry.title.trim() || nativeEntry(entry.url)?.key !== targetKey) return;
    const parent = nativeEntry(entry.source_url);
    if (!parent || nativeEntry(evidence.url)?.key !== parent.key) return;
    const target = new URL(targetKey), source = new URL(parent.key);
    const part = target.searchParams.get('p');
    if (!part || !/^\/video\/BV[0-9A-Za-z]{10}$/.test(target.pathname) ||
        source.search || source.origin !== target.origin || source.pathname !== target.pathname ||
        entry.page_number !== undefined && entry.page_number !== Number(part)) return;
    return parent.key;
  } catch { return; }
}

/** Called after relatedRecommendations validates the reference contract.
 * The server owns relevance, technical context, type admission and fault checks;
 * the UI checks fresh, source-linked data without promoting it to a verified page. */
export function hasEligibleReferenceLink(row: RelatedRecommendation): boolean {
  const { resource, reference } = row;
  if (resource.cache?.stale === true || failed.has(resource.fetch_status)) return false;
  if (!Object.prototype.hasOwnProperty.call(reference, 'link_eligible')) return hasVerifiedReferencePage(row);
  if (reference.link_eligible !== true) return false;
  if (reference.exact_teaching_verified !== false || !['observed', 'parent_course'].includes(reference.technical_context)) return false;
  const target = nativeEntry(resource.url);
  // Existing verified adapters keep their previous display behavior. A server
  // marker alone cannot make an arbitrary article a new search-only video card.
  if (!target) return hasVerifiedReferencePage(row);
  if (target.type !== resource.resource_type) return false;
  const parentSources = new Set<string>();
  const byId = new Map(row.evidence.map(evidence => [evidence.evidence_id, evidence]));
  let ownSource = false;
  for (const id of reference.evidence_ids) {
    const evidence = byId.get(id);
    if (!evidence || evidence.cache?.stale === true || !evidence.source?.trim() ||
        !['search', 'page', 'catalog'].includes(evidence.kind) ||
        ![evidence.title, evidence.snippet, evidence.text].some(text => typeof text === 'string' && text.trim())) return false;
    if (!reference.basis.includes(evidence.kind)) continue;
    if (nativeEntry(evidence.url)?.key === target.key) ownSource = true;
    const parent = catalogParentKey(evidence, target.key);
    if (parent) { parentSources.add(parent); ownSource = true; }
  }
  for (const alias of [resource.canonical_url, resource.resolved_url]) {
    if (alias) {
      const key = nativeEntry(alias)?.key;
      if (key !== target.key && (!key || !parentSources.has(key))) return false;
    }
  }
  return ownSource;
}

/** Keep the gallery concise while distinguishing search support from page facts. */
export function referenceLinkLabel(row: RelatedRecommendation): string | undefined {
  if (row.reference.link_eligible !== true) return;
  const labels: string[] = [];
  if (!row.reference.basis.some(kind => ['page', 'catalog'].includes(kind))) labels.push('搜索参考');
  else if (row.resource.resource_type === 'course') labels.push('课程参考');
  if (row.resource.requires_login === true) labels.push('需登录');
  if (row.resource.requires_payment === true) labels.push('需付费');
  if (row.resource.requires_enrollment === true) labels.push('需报名');
  return labels.length ? labels.join(' · ') : undefined;
}
