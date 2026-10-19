import type { CollectionCoverage, ResourceItem, ResultGroup, TopicEvidenceStatus } from './types';

export const resultSections = [
  { status: 'supported', items: 'items', platforms: 'platform_items', label: '明确主题推荐' },
  { status: 'partial', items: 'partial_items', platforms: 'partial_platform_items', label: '互补候选 · 部分覆盖' },
  { status: 'needs_review', items: 'review_items', platforms: 'review_platform_items', label: '待核实线索' },
] as const;
const statusOrder: Record<TopicEvidenceStatus, number> = { supported: 0, partial: 1, needs_review: 2 };
export type VisibleItem = { item: ResourceItem; status: TopicEvidenceStatus };

export const topicStatusNames: Record<TopicEvidenceStatus, string> = {
  supported: '直接支持', partial: '部分覆盖', needs_review: '待核',
};

// A reference only supports this card when its record is present on this item.
// Access restrictions and policy records cannot supply topic support.
export function topicEvidenceIds(item: ResourceItem, ids: string[] | undefined): string[] {
  const available = new Set(item.evidence.filter(record => ['search', 'page', 'catalog'].includes(record.kind)).map(record => record.evidence_id));
  return [...new Set((ids || []).filter(id => typeof id === 'string' && id.trim() && available.has(id)))];
}

export function topicStatus(item: ResourceItem, placement: TopicEvidenceStatus = 'supported'): TopicEvidenceStatus {
  const declared = item.match.topic_evidence_status;
  if (placement === 'needs_review' || !['supported', 'partial'].includes(declared || '')) return 'needs_review';
  if (!topicEvidenceIds(item, item.match.supporting_evidence_ids).length) return 'needs_review';
  return declared === 'partial' || placement === 'partial' ? 'partial' : 'supported';
}

export function supportedSubtopicIds(item: ResourceItem, id: string): string[] {
  const coverage = item.match.subtopic_coverage?.find(part => part.id === id);
  const supporting = new Set(topicEvidenceIds(item, item.match.supporting_evidence_ids));
  return coverage?.status === 'supported' ? topicEvidenceIds(item, coverage.evidence_ids).filter(evidenceId => supporting.has(evidenceId)) : [];
}

export function groupItems(group: ResultGroup): ResourceItem[] {
  return resultSections.flatMap(section => [...(group[section.items] || []), ...Object.values(group[section.platforms] || {}).flat()]);
}

export function visibleGroupItems(group: ResultGroup, platform: string, type: string, limit: number): VisibleItem[] {
  const known = new Map<string, VisibleItem>();
  for (const section of resultSections) for (const item of [...(group[section.items] || []), ...Object.values(group[section.platforms] || {}).flat()]) {
    const status = topicStatus(item, section.status);
    const previous = known.get(item.resource.resource_id);
    // A platform bucket cannot override the same resource's weaker topic evidence.
    if (!previous || statusOrder[status] > statusOrder[previous.status]) known.set(item.resource.resource_id, { item, status });
  }
  const unique = new Map<string, VisibleItem>();
  for (const section of resultSections) {
    const rows = platform === 'all' ? group[section.items] || [] : group[section.platforms]?.[platform] ?? (group[section.items] || []).filter(item => item.resource.platform === platform);
    for (const candidate of rows) {
      const row = known.get(candidate.resource.resource_id)!;
      const { item } = row;
      if (platform !== 'all' && item.resource.platform !== platform) continue;
      const kind = item.resource.resource_type;
      if (type === 'learning' && !['video', 'course', 'playlist'].includes(kind)) continue;
      if (type === 'text' && !['article', 'documentation', 'text'].includes(kind)) continue;
      if (type === 'unknown' && ['video', 'course', 'playlist', 'article', 'documentation', 'text'].includes(kind)) continue;
      unique.set(item.resource.resource_id, row);
    }
  }
  const bounded = Number.isSafeInteger(limit) && limit > 0 ? limit : 5;
  return resultSections.flatMap(section => [...unique.values()].filter(row => row.status === section.status).slice(0, bounded));
}

export function collectionCoverageRows(coverage: CollectionCoverage | undefined, items: VisibleItem[]) {
  if (coverage?.decomposition_status !== 'applied') return [];
  const subtopics = [...new Map(coverage.subtopics.map(part => [part.id, part])).values()];
  return subtopics.map(part => ({ part, sources: items.filter(row => row.status !== 'needs_review').flatMap(({ item }) => {
    const ids = supportedSubtopicIds(item, part.id);
    return ids.length ? [{ item, ids }] : [];
  }) }));
}
