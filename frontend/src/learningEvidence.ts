import { contentEvidence, normalizedUrl } from './contentEvidence.ts';
import type { ProjectKnowledgePoint } from './projectTypes';
import type { Evidence, ResourceItem, ResultGroup, TeachingSupport } from './types';
import type { VisibleItem } from './topicEvidence';

export type SkillSource = { item: ResourceItem; evidence: Evidence; quote: string; basis: TeachingSupport['basis'] };
export type SkillLearningRow = { id: string; text: string; content: SkillSource[]; titles: SkillSource[] };
export type LegacyLearningClue = { text: string; source: SkillSource };

export function transferableSkills(point: Pick<ProjectKnowledgePoint, 'learning_skills'>): string[] {
  const skills = point.learning_skills;
  return Array.isArray(skills) && skills.length <= 6 && skills.every(text => typeof text === 'string' && !!text.trim() && text === text.trim() && [...text].length <= 120)
    && new Set(skills).size === skills.length ? skills : [];
}

export function parseLearningSkills(text: string): { skills: string[]; error: string | null } {
  const skills = text.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  const error = skills.length > 6 ? '每个单元最多填写 6 条可迁移技能。'
    : skills.some(value => [...value].length > 120) ? '每条可迁移技能请控制在 120 字以内。'
    : new Set(skills).size !== skills.length ? '请合并重复的技能，每条只写一次。' : null;
  return { skills, error };
}

type EvidenceMaterial = Pick<ResourceItem, 'resource' | 'evidence'>;
function ownUrls(item: EvidenceMaterial): Set<string | undefined> {
  return new Set([item.resource.url, item.resource.canonical_url, item.resource.resolved_url].map(normalizedUrl).filter(Boolean));
}
function ownField(item: EvidenceMaterial, record: Evidence, field: string): boolean {
  const provenance = item.resource.field_provenance[field];
  return !!provenance && typeof provenance === 'object' && 'evidence_id' in provenance && 'source' in provenance && 'url' in provenance
    && provenance.evidence_id === record.evidence_id && provenance.source === record.source && typeof provenance.url === 'string'
    && normalizedUrl(provenance.url) === normalizedUrl(record.url) && ownUrls(item).has(normalizedUrl(record.url));
}
function uniqueRecord(item: EvidenceMaterial, id: string): Evidence | undefined {
  const records = item.evidence.filter(record => record.evidence_id === id);
  return records.length === 1 ? records[0] : undefined;
}
export function materialIdentity(item: EvidenceMaterial): boolean {
  const resource = item.resource;
  if (!['video', 'course', 'playlist'].includes(resource.resource_type) || !['fetched', 'success'].includes(resource.fetch_status)
    || !['page', 'catalog'].includes(resource.metadata_evidence_level)) return false;
  if (resource.resource_type !== 'video') return true;
  return boundVideoIdentity(item);
}
export function boundVideoIdentity(item: EvidenceMaterial): boolean {
  const resource = item.resource;
  if (resource.video_evidence_status !== 'page_verified') return false;
  const provenance = resource.field_provenance.video_evidence_status;
  if (!provenance || typeof provenance !== 'object' || !('evidence_id' in provenance) || typeof provenance.evidence_id !== 'string') return false;
  const record = uniqueRecord(item, provenance.evidence_id);
  return !!record && record.kind === 'page' && record.field === 'video_evidence_status' && ownField(item, record, 'video_evidence_status');
}
export function ownTitle(item: EvidenceMaterial, record: Evidence): boolean {
  return record.kind === 'page' && record.field === 'title' && record.text === item.resource.title && ownField(item, record, 'title');
}
function boundedRows(result: ResultGroup | null | undefined, rows: VisibleItem[]): VisibleItem[] {
  return rows.filter(row => row.status !== 'needs_review' && materialIdentity(row.item)
    && row.item.match.knowledge_point_id === result?.knowledge_point_id && row.item.match.resource_id === row.item.resource.resource_id);
}

// Only referenced own records and bound lesson summaries are hashed. A hash is
// integrity/binding evidence, never proof that the lesson teaches a parameter.
export function learningEvidenceTexts(rows: VisibleItem[]): string[] {
  const texts = new Set<string>();
  for (const { item } of rows) {
    const ids = new Set((item.match.teaching_support || []).map(row => row.evidence_id));
    for (const record of item.evidence) if (ids.has(record.evidence_id) && typeof record.text === 'string' && record.text.length <= 100_000) texts.add(record.text);
    const summary = item.resource.video_topic_summary;
    if (typeof summary === 'string' && [...summary].length <= 6000) texts.add(summary);
  }
  return [...texts];
}

export function skillLearningRows(planned: ProjectKnowledgePoint, result: ResultGroup | null | undefined, rows: VisibleItem[], digests: Map<string, string>): SkillLearningRow[] {
  const skills = transferableSkills(planned), coverage = result?.learning_coverage;
  const visible = boundedRows(result, rows);
  const contentCache = new Map(visible.map(row => [row.item.resource.resource_id, contentEvidence(row.item, digests)]));
  return skills.map((text, index) => {
    const id = `skill_${index + 1}`, matches = coverage?.mode === 'transferable_skills' && Array.isArray(coverage.skills) ? coverage.skills.filter(row => row.id === id) : [];
    const aggregate = matches.length === 1 && matches[0].text === text ? matches[0] : undefined;
    const content = new Map<string, SkillSource>(), titles = new Map<string, SkillSource>();
    if (aggregate) for (const { item } of visible) for (const claim of item.match.teaching_support || []) {
      if (claim.skill_id !== id || claim.skill !== text || !Array.isArray(aggregate.evidence_ids) || !aggregate.evidence_ids.includes(claim.evidence_id)
        || !['title', 'description', 'catalog', 'lesson_notes'].includes(claim.basis) || !/^[a-f0-9]{64}$/.test(claim.source_text_sha256)) continue;
      const record = uniqueRecord(item, claim.evidence_id);
      if (!record || typeof record.text !== 'string' || typeof claim.quote !== 'string' || !claim.quote.trim() || !record.text.includes(claim.quote)
        || digests.get(record.text) !== claim.source_text_sha256 || /search|snippet/i.test(record.source) || !ownUrls(item).has(normalizedUrl(record.url))) continue;
      const source = { item, evidence: record, quote: claim.quote, basis: claim.basis };
      if (claim.basis === 'title') {
        if (Array.isArray(aggregate.title_resource_ids) && aggregate.title_resource_ids.includes(item.resource.resource_id) && ownTitle(item, record)) titles.set(item.resource.resource_id, source);
        continue;
      }
      if (!Array.isArray(aggregate.content_resource_ids) || !aggregate.content_resource_ids.includes(item.resource.resource_id)
        || !contentCache.get(item.resource.resource_id)?.some(row => row.evidence_id === record.evidence_id)) continue;
      const compatible = claim.basis === 'description' ? record.kind === 'page' && record.field === 'description' && ownField(item, record, 'description')
        : claim.basis === 'catalog' ? record.kind === 'catalog' && /^chapters\.\d+$/.test(record.field || '')
        : record.kind === 'page' && record.field === 'video_topic_summary' && ownField(item, record, 'video_topic_summary');
      if (compatible) content.set(item.resource.resource_id, source);
    }
    return { id, text, content: [...content.values()], titles: [...titles.values()].filter(row => !content.has(row.item.resource.resource_id)) };
  });
}

// Legacy match-only API cores are clues, not newly invented transferable skill
// goals. Search titles and review-only resources never enter this lane.
export function legacyLearningClues(result: ResultGroup | null | undefined, rows: VisibleItem[]): LegacyLearningClue[] {
  const clues = new Map<string, LegacyLearningClue>();
  for (const { item } of boundedRows(result, rows)) for (const part of item.match.subtopic_coverage || []) {
    if (!/^api_operation_core_\d+$/.test(part.id) || part.status !== 'supported' || !part.text?.trim()) continue;
    for (const id of part.evidence_ids) {
      if (!item.match.supporting_evidence_ids?.includes(id)) continue;
      const record = uniqueRecord(item, id);
      if (!record || !ownTitle(item, record) || /search|snippet/i.test(record.source)) continue;
      const key = `${item.resource.resource_id}:${part.id}`;
      clues.set(key, { text: part.text, source: { item, evidence: record, quote: record.text!, basis: 'title' } });
    }
  }
  return [...clues.values()];
}
