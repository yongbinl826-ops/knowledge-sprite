import { contentEvidence, normalizedUrl } from './contentEvidence.ts';
import { boundVideoIdentity, materialIdentity, ownTitle, transferableSkills } from './learningEvidence.ts';
import type { ProjectKnowledgePoint } from './projectTypes';
import type { Chapter, Evidence, RelatedTopicPointer, ResultGroup } from './types';

export type ValidTopicPointer = RelatedTopicPointer & { targetUrl: string };
const nativeParts = 'html.bilibili.__INITIAL_STATE__.videoData.pages';
const boundedText = (text: unknown, limit: number): text is string => typeof text === 'string' && !!text.trim() && text === text.trim() && [...text].length <= limit;

// Only an observed own chapter URL is allowed. In particular, an ordinal or a
// number in the title never creates a Bili ?p= destination.
function catalogTarget(entry: RelatedTopicPointer, chapter: Chapter, record: Evidence): string | undefined {
  const source = normalizedUrl(record.url), canonical = normalizedUrl(entry.resource.canonical_url);
  if (!source || source !== record.url || source !== canonical || entry.pointer.source_url !== record.url) return undefined;
  const nativeOwner = /^https:\/\/www\.bilibili\.com\/video\/BV[A-Za-z0-9]{10}\/$/.test(source);
  const base = new URL(source);
  const ownContext = [entry.resource.url, entry.resource.canonical_url, entry.resource.resolved_url].filter(Boolean).every(value => {
    const owner = normalizedUrl(value);
    if (!owner) return false;
    const parsed = new URL(owner);
    return nativeOwner ? parsed.origin === base.origin && parsed.pathname === base.pathname : owner === source;
  });
  if (!ownContext) return undefined;
  const target = normalizedUrl(chapter.url || record.url);
  if (!target || entry.pointer.target_url !== (chapter.url || record.url) || entry.pointer.target_url !== target) return undefined;
  const nativeSource = record.source === nativeParts || chapter.source === nativeParts;
  if (!nativeSource) return target === source ? target : undefined;
  if (!nativeOwner) return undefined;
  const facts = JSON.parse(record.text!) as Record<string, unknown>;
  const nativeChapter = chapter as Chapter & { source_url?: unknown; page_number?: unknown };
  const number = new URL(target).searchParams.get('p');
  return chapter.source === nativeParts && record.source === nativeParts
    && nativeChapter.source_url === source && facts.source_url === source
    && typeof nativeChapter.page_number === 'number' && Number.isSafeInteger(nativeChapter.page_number) && nativeChapter.page_number > 0 && nativeChapter.page_number <= 999_999_999
    && facts.page_number === nativeChapter.page_number && facts.url === chapter.url
    && number === String(nativeChapter.page_number) && target === `${source}?p=${number}` ? target : undefined;
}

export function topicPointerEvidenceTexts(result: ResultGroup | null | undefined): string[] {
  const texts = new Set<string>();
  for (const entry of (Array.isArray(result?.related_topic_pointers) ? result.related_topic_pointers : []).slice(0, 4)) {
    if (!entry || !entry.pointer || !Array.isArray(entry.evidence)) continue;
    for (const record of entry.evidence || []) if (record.evidence_id === entry.pointer?.evidence_id
      && typeof record.text === 'string' && record.text.length <= 100_000) texts.add(record.text);
  }
  return [...texts];
}

// A pointer confirms only that an original catalog names a related topic.
// This helper has no path into learning_coverage, teaching_support or card rows.
export function relatedTopicPointers(planned: ProjectKnowledgePoint, result: ResultGroup | null | undefined, platform: string, digests: Map<string, string>): ValidTopicPointer[] {
  if (!result || result.scope_status === 'mismatch') return [];
  const skills = transferableSkills(planned), seen = new Set<string>();
  return (Array.isArray(result.related_topic_pointers) ? result.related_topic_pointers : []).slice(0, 4).flatMap(entry => {
    if (!entry || !entry.resource || !Array.isArray(entry.evidence) || !entry.pointer) return [];
    const { resource, pointer } = entry;
    if ((platform !== 'all' && resource.platform !== platform) || pointer.scope !== 'topic_declared' || pointer.basis !== 'catalog'
      || pointer.knowledge_point_id !== result.knowledge_point_id || pointer.resource_id !== resource.resource_id
      || !/^skill_[1-6]$/.test(pointer.skill_id) || skills[Number(pointer.skill_id.slice(6)) - 1] !== pointer.skill
      || !boundedText(pointer.quote, 180) || !/^[a-f0-9]{64}$/.test(pointer.source_text_sha256)
      || !Array.isArray(pointer.missing_components) || !pointer.missing_components.length || pointer.missing_components.length > 12
      || !pointer.missing_components.every(text => boundedText(text, 180)) || !Array.isArray(resource.chapters)
      || !resource.field_provenance || !materialIdentity(entry) || !boundVideoIdentity(entry)) return [];
    // Reject ambiguous record IDs, rather than borrowing an adjacent row.
    if (new Set(entry.evidence.map(row => row.evidence_id)).size !== entry.evidence.length) return [];
    if (!entry.evidence.some(record => ownTitle(entry, record) && !/search|snippet|sitemap|discovery/i.test(record.source))) return [];
    const proof = resource.field_provenance.video_evidence_status as { evidence_id?: string };
    if (!entry.evidence.some(record => record.evidence_id === proof.evidence_id && !/search|snippet|sitemap|discovery/i.test(record.source))) return [];
    const record = entry.evidence.find(row => row.evidence_id === pointer.evidence_id);
    if (!record || record.kind !== 'catalog' || !/^chapters\.\d+$/.test(record.field || '')
      || !record.source || /search|snippet|sitemap|discovery/i.test(record.source) || typeof record.text !== 'string'
      || !record.text.includes(pointer.quote) || digests.get(record.text) !== pointer.source_text_sha256
      || !contentEvidence(entry, digests).some(row => row.evidence_id === record.evidence_id)) return [];
    const chapter = resource.chapters[Number(record.field!.split('.')[1])];
    if (chapter.title !== pointer.quote || chapter.source !== record.source) return [];
    let targetUrl: string | undefined;
    try { targetUrl = catalogTarget(entry, chapter, record); } catch { return []; }
    if (!targetUrl) return [];
    const key = JSON.stringify([resource.resource_id, pointer.skill_id, pointer.evidence_id, targetUrl]);
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ ...entry, targetUrl }];
  });
}
