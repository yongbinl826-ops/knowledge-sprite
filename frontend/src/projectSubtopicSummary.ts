import { supportedSubtopicIds, visibleGroupItems } from './topicEvidence.ts';
import { externalUrl } from './safeUrls.ts';
import type { ResultGroup } from './types';

// Summarize the existing backend targets, never invent a new learning split.
// A collection claim alone cannot promote an unknown or an unseen card.
export function projectSubtopicSummary(group: ResultGroup, limit = 5) {
  const coverage = group.collection_coverage;
  if (coverage?.decomposition_status !== 'applied') return [];
  const parts = coverage.subtopics;
  if (new Set(parts.map(part => part.id)).size !== parts.length) return [];
  const visible = visibleGroupItems(group, 'all', 'learning', group.section_limit || limit)
    .filter(({ item, status }) => status !== 'needs_review' && !!externalUrl(item.resource.url)
      && item.match.knowledge_point_id === group.knowledge_point_id
      && item.match.resource_id === item.resource.resource_id);
  if (!visible.length) return [];
  return parts.filter(part => part.text.trim()).map(part => ({
    id: part.id, text: part.text,
    supported: part.status === 'supported' && visible.some(({ item }) => {
      const own = item.match.subtopic_coverage?.find(candidate => candidate.id === part.id);
      if (!own || own.text !== part.text || !part.resource_ids.includes(item.resource.resource_id)) return false;
      return supportedSubtopicIds(item, part.id).some(id => part.evidence_ids.includes(id));
    }),
  }));
}
