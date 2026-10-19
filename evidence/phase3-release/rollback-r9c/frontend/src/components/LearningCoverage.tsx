import { externalUrl } from '../api';
import { collectionCoverageRows, type VisibleItem } from '../topicEvidence';
import type { Evidence, ResourceItem, ResultGroup } from '../types';
import type { ProjectKnowledgePoint } from '../projectTypes';
import { useEffect, useState } from 'react';
import { groupCoverageRows } from '../coverageDisplay';

const chapterFields = ['title', 'url', 'start_seconds', 'end_seconds', 'duration_seconds'] as const;
const fccVideoSource = 'html.freecodecamp.course_announcement.video';
const fccSummarySource = 'html.freecodecamp.course_announcement.summary';
const twtSource = 'html.techwithtim.lesson.';
const twtSummaryLimit = 6000;
const twtDomBinding = 'One visible own lesson title and teaching notes share a unique visible embedded video in the same lesson content container.';
function normalizedUrl(value: string | null | undefined) {
  const safe = externalUrl(value || '');
  if (!safe) return undefined;
  const url = new URL(safe);
  url.hash = '';
  return url.href;
}

function fccAnnouncement(value: string | null | undefined) {
  const normalized = normalizedUrl(value);
  if (!normalized) return undefined;
  const url = new URL(normalized);
  return url.protocol === 'https:' && !url.port && ['freecodecamp.org', 'www.freecodecamp.org'].includes(url.hostname)
    && /^\/news\/[a-z0-9][a-z0-9-]{1,180}\/?$/.test(url.pathname) ? normalized : undefined;
}
function youtubeId(value: unknown, embed: boolean) {
  if (typeof value !== 'string') return undefined;
  const normalized = normalizedUrl(value);
  if (!normalized) return undefined;
  const url = new URL(normalized);
  if (url.protocol !== 'https:' || url.port) return undefined;
  if (embed) return ['www.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname) && !url.search
    ? /^\/embed\/([A-Za-z0-9_-]{11})$/.exec(url.pathname)?.[1] : undefined;
  if (url.hostname === 'youtu.be' && !url.search) return /^\/([A-Za-z0-9_-]{11})$/.exec(url.pathname)?.[1];
  const ids = url.searchParams.getAll('v');
  return url.hostname === 'www.youtube.com' && url.pathname === '/watch' && url.searchParams.size === 1
    && ids.length === 1 && /^[A-Za-z0-9_-]{11}$/.test(ids[0]) ? ids[0] : undefined;
}
function twtLesson(value: string | null | undefined) {
  const normalized = normalizedUrl(value);
  if (!normalized) return undefined;
  const url = new URL(normalized);
  return url.protocol === 'https:' && !url.port && !url.search && ['techwithtim.net', 'www.techwithtim.net'].includes(url.hostname)
    && /^\/tutorials\/[a-z0-9][a-z0-9-]{0,120}\/[a-z0-9][a-z0-9-]{0,120}\/[a-z0-9][a-z0-9-]{0,120}\/?$/.test(url.pathname) ? normalized : undefined;
}
function twtSummaryEvidence(item: ResourceItem, digest: string | undefined): Evidence[] {
  const { resource } = item;
  const summary = resource.video_topic_summary;
  if (!twtLesson(resource.url) || typeof resource.title !== 'string' || !resource.title.trim() || resource.resource_type !== 'video' || resource.video_evidence_status !== 'page_verified'
    || !['fetched', 'success'].includes(resource.fetch_status) || !['page', 'catalog'].includes(resource.metadata_evidence_level)
    || typeof summary !== 'string' || !summary.trim() || [...summary].length > twtSummaryLimit || !digest) return [];
  const own = new Set([resource.url, resource.canonical_url, resource.resolved_url].map(twtLesson).filter(Boolean));
  const bound = (field: string, suffix: string) => {
    const source = twtSource + suffix;
    const provenance = resource.field_provenance[field];
    if (!provenance || typeof provenance !== 'object' || !('evidence_id' in provenance) || !('source' in provenance)
      || !('url' in provenance) || provenance.source !== source || typeof provenance.url !== 'string') return undefined;
    const records = item.evidence.filter(record => record.evidence_id === provenance.evidence_id);
    if (records.length !== 1) return undefined;
    const record = records[0]; const page = twtLesson(record.url);
    return record.kind === 'page' && record.field === field && record.source === source && page && own.has(page)
      && twtLesson(provenance.url) === page ? record : undefined;
  };
  const title = bound('title', 'title'), proof = bound('video_evidence_status', 'video'), body = bound('video_topic_summary', 'summary');
  if (!title || !proof || !body || title.text !== resource.title || body.text !== summary
    || new Set([title.url, proof.url, body.url].map(normalizedUrl)).size !== 1 || summary.split('\n')[0] !== resource.title) return [];
  try {
    const parsed: unknown = JSON.parse(proof.text || '');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return [];
    const facts = parsed as Record<string, unknown>;
    const titleKey = (value: unknown) => typeof value === 'string' ? value.toLowerCase().trim().replace(/\s+/g, ' ') : undefined;
    const statement = facts.teaching_binding;
    const legacyBinding = !('binding_version' in facts) && !('binding_kind' in facts) && !('dom_witness' in facts)
      && typeof statement === 'string' && /\bthe video above offers more in[- ]depth explanations\b/i.test(statement)
      && !/\b(?:not|never|doesn't|cannot)\b/i.test(statement);
    const witness = facts.dom_witness;
    const dom = witness && typeof witness === 'object' && !Array.isArray(witness) ? witness as Record<string, unknown> : undefined;
    const domBinding = facts.binding_version === 2 && facts.binding_kind === 'same_lesson_dom_v2' && statement === twtDomBinding && !!dom
      && ['content_count', 'heading_count', 'markdown_count', 'embedded_iframe_count', 'all_content_iframe_count'].every(key => dom[key] === 1)
      && dom.visible === true && dom.heading_text === resource.title && dom.iframe_title === facts.embed_title
      && dom.notes_sha256 === digest && dom.notes_characters === [...summary].length
      && typeof dom.teaching_prose_count === 'number' && Number.isSafeInteger(dom.teaching_prose_count) && dom.teaching_prose_count >= 2 && dom.teaching_prose_count <= 200;
    if (facts.lesson_title !== resource.title || typeof facts.lesson_url !== 'string' || twtLesson(facts.lesson_url) !== twtLesson(proof.url)
      || titleKey(facts.embed_title) !== titleKey(resource.title) || typeof facts.video_id !== 'string' || !/^[A-Za-z0-9_-]{11}$/.test(facts.video_id)
      || youtubeId(facts.embed_url, true) !== facts.video_id || (!legacyBinding && !domBinding)
      || facts.summary_sha256 !== digest) return [];
    return [body];
  } catch { return []; }
}
function fccSummaryEvidence(item: ResourceItem): Evidence[] {
  const { resource } = item;
  const summary = resource.video_topic_summary;
  if (!fccAnnouncement(resource.url) || typeof resource.title !== 'string' || !resource.title.trim() || resource.resource_type !== 'video' || resource.video_evidence_status !== 'page_verified'
    || !['fetched', 'success'].includes(resource.fetch_status) || !['page', 'catalog'].includes(resource.metadata_evidence_level)
    || typeof summary !== 'string' || !summary.trim() || [...summary].length > 1800) return [];
  const own = new Set([resource.url, resource.canonical_url, resource.resolved_url].map(fccAnnouncement).filter(Boolean));
  const bound = (field: string, source: string) => {
    const provenance = resource.field_provenance[field];
    if (!provenance || typeof provenance !== 'object' || !('evidence_id' in provenance) || !('source' in provenance)
      || !('url' in provenance) || provenance.source !== source || typeof provenance.url !== 'string') return undefined;
    const records = item.evidence.filter(record => record.evidence_id === provenance.evidence_id);
    if (records.length !== 1) return undefined;
    const record = records[0];
    const page = fccAnnouncement(record.url);
    return record.kind === 'page' && record.field === field && record.source === source && page && own.has(page)
      && fccAnnouncement(provenance.url) === page ? record : undefined;
  };
  const proof = bound('video_evidence_status', fccVideoSource);
  const body = bound('video_topic_summary', fccSummarySource);
  if (!proof || !body || body.text !== summary || normalizedUrl(proof.url) !== normalizedUrl(body.url)) return [];
  try {
    const binding: unknown = JSON.parse(proof.text || '');
    if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return [];
    const facts = binding as Record<string, unknown>;
    const announcement = facts.announcement;
    if (facts.course_title !== resource.title || typeof announcement !== 'string'
      || !/freeCodeCamp(?:\.org)?\s+YouTube\s+channel/i.test(announcement)
      || !/\b(?:course|tutorial)\b/i.test(announcement) || !/\b(?:published|released|created|watch|learn|teaches?)\b/i.test(announcement)
      || summary.split('\n')[0] !== announcement || typeof facts.video_id !== 'string'
      || !/^[A-Za-z0-9_-]{11}$/.test(facts.video_id)
      || youtubeId(facts.watch_url, false) !== facts.video_id || youtubeId(facts.embed_url, true) !== facts.video_id) return [];
    return [body];
  } catch { return []; }
}

// A discovery title/snippet is useful for choosing a lead, but it cannot supply
// this learning checklist. Bind page descriptions and catalog rows to the
// visible resource's own fields; reject duplicate, missing or crossed IDs.
function contentEvidence(item: ResourceItem, digests: Map<string, string>): Evidence[] {
  // These announcements retain a specially bound video summary. Generic
  // Article metadata, titles, scripts and surrounding prose must never provide
  // a second path to coverage if that binding is absent or damaged.
  if (fccAnnouncement(item.resource.url)) return fccSummaryEvidence(item);
  if (twtLesson(item.resource.url)) return twtSummaryEvidence(item, digests.get(item.resource.video_topic_summary || ''));
  const origin = item.resource.field_provenance.video_evidence_status;
  if (item.resource.video_topic_summary != null || (origin && typeof origin === 'object' && 'source' in origin
    && [fccVideoSource, twtSource + 'video'].includes(String(origin.source)))) return [];
  const ownUrls = new Set([item.resource.url, item.resource.canonical_url, item.resource.resolved_url].map(normalizedUrl).filter(Boolean));
  const counts = new Map<string, number>();
  for (const record of item.evidence) counts.set(record.evidence_id, (counts.get(record.evidence_id) || 0) + 1);
  return item.evidence.filter(record => {
    if (counts.get(record.evidence_id) !== 1 || !record.text?.trim() || !ownUrls.has(normalizedUrl(record.url)) || /search|snippet/i.test(record.source)) return false;
    if (record.kind === 'page' && record.field === 'description') {
      const provenance = item.resource.field_provenance.description;
      return !!provenance && typeof provenance === 'object' && 'evidence_id' in provenance && 'source' in provenance
        && provenance.evidence_id === record.evidence_id && provenance.source === record.source
        && item.resource.description === record.text;
    }
    if (record.kind !== 'catalog' || !/^chapters\.\d+$/.test(record.field || '')) return false;
    const index = Number(record.field!.split('.')[1]);
    const chapter = item.resource.chapters[index];
    if (typeof chapter?.title !== 'string' || !chapter.title.trim() || chapter.evidence_id !== record.evidence_id || (chapter.url != null && !externalUrl(chapter.url))) return false;
    try {
      const fields: unknown = JSON.parse(record.text);
      if (!fields || typeof fields !== 'object' || Array.isArray(fields)) return false;
      const facts = fields as Record<string, unknown>;
      if (chapterFields.some(key => (facts[key] ?? null) !== (chapter[key] ?? null))) return false;
      const times = [chapter.start_seconds, chapter.end_seconds, chapter.duration_seconds];
      return times.every(value => value == null || (Number.isFinite(value) && value >= 0))
        && (chapter.duration_seconds == null || chapter.duration_seconds > 0)
        && !(chapter.start_seconds != null && chapter.end_seconds != null && chapter.end_seconds < chapter.start_seconds);
    } catch { return false; }
  });
}

export function LearningCoverage({ planned, result, rows, filtered, searching }: {
  planned: ProjectKnowledgePoint; result: ResultGroup | null | undefined; rows: VisibleItem[]; filtered: boolean; searching: boolean;
}) {
  const summaryKey = JSON.stringify([...new Set(rows.filter(row => twtLesson(row.item.resource.url)).map(row => row.item.resource.video_topic_summary)
    .filter((value): value is string => typeof value === 'string' && !!value.trim() && [...value].length <= twtSummaryLimit))]);
  const [digestState, setDigestState] = useState(() => ({ key: '', values: new Map<string, string>() }));
  useEffect(() => {
    const summaries = JSON.parse(summaryKey) as string[];
    if (!summaries.length) return;
    let stale = false;
    void Promise.all(summaries.map(async summary => {
      const buffer = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(summary));
      return [summary, [...new Uint8Array(buffer)].map(value => value.toString(16).padStart(2, '0')).join('')] as const;
    })).then(values => { if (!stale) setDigestState({ key: summaryKey, values: new Map(values) }); })
      .catch(() => { if (!stale) setDigestState({ key: summaryKey, values: new Map() }); });
    return () => { stale = true; };
  }, [summaryKey]);
  const digests = digestState.key === summaryKey ? digestState.values : new Map<string, string>();
  const checking = summaryKey !== '[]' && digestState.key !== summaryKey;
  const coverage = result?.collection_coverage;
  const unchecked = [...new Set((planned.concepts || []).map(text => text.trim()).filter(Boolean))];
  // Confirmed concepts remain learning requirements when an older result only
  // assessed the short unit name. A whole-topic match cannot fill those rows.
  const assessed = coverage?.subtopics.filter(part => {
    if (part.id.startsWith('learning_target_')) {
      const index = /^learning_target_([1-8])$/.exec(part.id);
      return !!index && unchecked[Number(index[1]) - 1] === part.text;
    }
    return part.id === 'whole_topic' ? part.text === result?.text : coverage.decomposition_status === 'applied';
  }) || [];
  const expected = new Map(assessed.map(part => [part.id, part.text]));
  const bounded = rows.filter(row => row.status !== 'needs_review'
    && row.item.match.knowledge_point_id === result?.knowledge_point_id
    && row.item.match.resource_id === row.item.resource.resource_id).map(row => ({ ...row, item: { ...row.item,
      evidence: contentEvidence(row.item, digests), match: { ...row.item.match,
        subtopic_coverage: row.item.match.subtopic_coverage?.filter(part => expected.get(part.id) === part.text),
      },
    } }));
  const assessedRows = coverage ? collectionCoverageRows({ ...coverage, decomposition_status: 'applied', subtopics: assessed }, bounded) : [];
  const pending = coverage ? unchecked.flatMap((text, index) => assessed.some(part => part.id !== 'whole_topic' && part.text === text) ? [] : [{
    part: { id: `learning_target_${index + 1}`, text, status: 'unknown' as const, resource_ids: [], evidence_ids: [] }, sources: [],
  }]) : [];
  const parts = groupCoverageRows([...assessedRows, ...pending].filter(row => row.part.text.trim()));
  const supported = parts.filter(row => row.sources.length);
  const missing = parts.filter(row => !row.sources.length);
  const first = supported.flatMap(row => row.sources).find(source => externalUrl(source.item.resource.url));
  const firstUrl = first && externalUrl(first.item.resource.url);
  const practice = planned.practice_check || planned.project_task || planned.learning_goal;
  return <aside className="unit-coverage" aria-label={`${planned.name}的学习路线`}>
    <div className="unit-coverage-heading"><h5>本单元学习路线</h5><span role="status">{checking ? '正在核对内容依据…' : parts.length ? `${supported.length} / ${parts.length} 项有内容依据` : '子技能覆盖待确认'}</span></div>
    {parts.length ? <div className="unit-coverage-columns">
      <div className="unit-coverage-supported"><h6>视频可支持</h6>{supported.length ? <ul>{supported.map(({ key, text, memberIds, sources }) => <li key={key} data-requirement-ids={JSON.stringify(memberIds)}><span>{text}</span><small>{sources.length} 个当前视频有正文或目录依据</small></li>)}</ul> : <p>这些学习目标尚无足够的本课正文或目录依据。</p>}</div>
      <div className="unit-coverage-missing"><h6>仍需补充</h6>{missing.length ? <ul>{missing.map(({ key, text, memberIds }) => <li key={key} data-requirement-ids={JSON.stringify(memberIds)}>{text}</li>)}</ul> : <p>已列子技能均找到内容依据，仍需核对深度与完整性。</p>}</div>
    </div> : <p className="unit-coverage-unknown">现有信息尚不足以逐项确认教学内容。{unchecked.length ? `学习时请核对：${unchecked.join('、')}。` : `请对照学习目标「${planned.learning_goal}」核对视频简介或目录。`}</p>}
    <div className="unit-coverage-next"><strong>下一步</strong><p>{firstUrl ? missing.length ? '先学习已有内容依据的部分，再为仍需补充的子技能寻找视频或资料。' : '先对照视频学习，再用下面的项目练习检验。' : searching ? '检索仍在进行，先保留这个学习目标，等待课程与内容依据返回。' : filtered ? '切换到「全部平台」核对其他视频；仍缺内容时，返回调整知识点后重新检索。' : rows.length ? '先到原平台核对简介或目录；待核实线索和搜索摘要不计入已支持的子技能。' : '返回调整知识点，明确本单元的目标与工具后重新检索。'}</p>
      {firstUrl && <a href={firstUrl} target="_blank" rel="noopener noreferrer">打开首个有依据的视频 <span aria-hidden="true">↗</span><span className="sr-only">：{first.item.resource.title}（在新窗口打开）</span></a>}
    </div>
    {practice && <p className="unit-coverage-practice"><strong>项目练习</strong><span>{practice}</span></p>}
    <p className="unit-coverage-note">仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。</p>
  </aside>;
}
