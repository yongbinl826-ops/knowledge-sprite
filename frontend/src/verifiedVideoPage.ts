import type { RelatedRecommendation, Resource } from './types';

export type VideoPageFacts = Partial<Pick<Resource,
  'fetch_status' | 'video_evidence_status' | 'cache' | 'requires_payment'>>;

/** A verified page is eligible for a card, not proof of complete playback. */
export function isVerifiedVideoPage(resource: VideoPageFacts): boolean {
  return ['fetched', 'success'].includes(resource.fetch_status || '') &&
    resource.video_evidence_status === 'page_verified' &&
    resource.cache?.stale !== true && resource.requires_payment !== true;
}

export function hasVerifiedReferencePage(row: RelatedRecommendation): boolean {
  if (!isVerifiedVideoPage(row.resource) || !row.reference.basis.some(kind => ['page', 'catalog'].includes(kind))) return false;
  const supporting = new Set(row.reference.evidence_ids);
  return row.evidence.some(evidence => supporting.has(evidence.evidence_id) &&
    ['page', 'catalog'].includes(evidence.kind) && evidence.cache?.stale !== true);
}
