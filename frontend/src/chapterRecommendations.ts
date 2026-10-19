import type { Chapter, Evidence, ResourceItem } from './types';

export type ChapterRecommendation = {
  title: string;
  evidenceId: string;
  sourceUrl: string;
  chapterUrl?: string;
  ordinal: number;
};

function safeUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value || value.length > 8192 || value.trim() !== value || /[\u0000-\u001f\u007f\\]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}

function validTimes(value: { start_seconds?: unknown; end_seconds?: unknown; duration_seconds?: unknown }): boolean {
  const { start_seconds: start, end_seconds: end, duration_seconds: duration } = value;
  const valid = (seconds: unknown, isDuration = false) => seconds == null || (typeof seconds === 'number' && Number.isFinite(seconds) && (isDuration ? seconds > 0 : seconds >= 0));
  return valid(start) && valid(end) && valid(duration, true) && !(typeof start === 'number' && typeof end === 'number' && end < start);
}

function verifiedChapters(item: ResourceItem): ChapterRecommendation[] {
  const records = new Map<string, Evidence[]>();
  for (const record of item.evidence || []) records.set(record.evidence_id, [...(records.get(record.evidence_id) || []), record]);
  return (item.resource.chapters || []).flatMap((chapter: Chapter, index) => {
    if (!chapter || typeof chapter.title !== 'string' || !chapter.title.trim() || typeof chapter.evidence_id !== 'string' || !chapter.evidence_id.trim()) return [];
    const matching = records.get(chapter.evidence_id);
    if (matching?.length !== 1) return [];
    const record = matching[0];
    const sourceUrl = safeUrl(record.url);
    if (record.kind !== 'catalog' || record.field !== `chapters.${index}` || !sourceUrl) return [];
    let fields: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(record.text || '');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return [];
      fields = parsed as Record<string, unknown>;
    } catch { return []; }
    const keys = ['title', 'url', 'start_seconds', 'end_seconds', 'duration_seconds'] as const;
    if (keys.some(key => (fields[key] ?? null) !== (chapter[key] ?? null)) || !validTimes(fields) || !validTimes(chapter)) return [];
    const chapterUrl = chapter.url == null ? undefined : safeUrl(chapter.url);
    if (chapter.url != null && !chapterUrl) return [];
    return [{ title: chapter.title, evidenceId: record.evidence_id, sourceUrl, ...(chapterUrl ? { chapterUrl } : {}), ordinal: index + 1 }];
  });
}

// These are spelling equivalents, not inferred teaching coverage. A specific
// topic must occur in the chapter title; the course title supplies language only.
const aliases = [
  /列表|\blists?\b/gi,
  /字典|\bdict(?:ionary|ionaries)?\b/gi,
  /元组|\btuples?\b/gi,
  /集合|\bsets?\b/gi,
  /字符串|\bstrings?\b/gi,
  /函数|\bfunctions?\b/gi,
  /循环|\bloops?\b/gi,
  /递归|\brecursi(?:on|ve)\b/gi,
  /推导式|\bcomprehensions?\b/gi,
  /遍历|迭代|\biterat(?:ion|ing|e|ors?)\b/gi,
  /排序|\bsort(?:ing)?\b/gi,
  /异常|\bexceptions?\b/gi,
  /错误处理|\berror handling\b/gi,
  /并发(?:控制)?|\bconcurren(?:cy|t)\b/gi,
  /面向对象|\bobject[- ]oriented\b|\boop\b/gi,
  /数据结构|\bdata structures?\b/gi,
  /文件|\bfiles?\b/gi,
  /变量|\bvariables?\b/gi,
  /条件(?:语句)?|分支|\bconditionals?\b/gi,
];
const languages = [
  /\bpython(?:\s*v?\d+(?:\.\d+)*)?\b/gi,
  /\bjavascript\b/gi,
  /\btypescript\b/gi,
  /\bjava\b/gi,
  /(?<![a-z0-9])c\+\+(?:\d+)?(?![a-z0-9])/gi,
  /(?<![a-z0-9])c#(?:\d+)?(?![a-z0-9])/gi,
];
const generic = /编程语言|语言|基础知识|基础|入门|知识点|教程|学习|掌握|了解|理解|相关|介绍|使用|操作|应用|\b(?:programming|language|basics?|fundamentals?|introduction|intro|tutorials?|learn(?:ing)?|using|usage|of|the|a|an|to|with|in)\b/gi;
const introduction = /基础|入门|概述|概论|导论|初识|介绍|绪论|开始|\b(?:basics?|fundamentals?|introduction|intro|getting started|overview)\b/i;
const assessment = /测验|考试|作业|习题|测试题|练习题|先修|前置要求|\b(?:quiz(?:zes)?|exam(?:ination)?s?|assignments?|homework|prerequisites?)\b/i;
const clean = (value: string) => value.toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, '');
const matches = (expression: RegExp, value: string) => { expression.lastIndex = 0; return expression.test(value); };

type Topic = { languages: number[]; parts: { concepts: number[]; words: string[]; literal: string }[] };
function topicFor(point: string): Topic {
  const contexts = languages.flatMap((pattern, index) => matches(pattern, point) ? [index] : []);
  let withoutLanguage = point;
  for (const pattern of languages) withoutLanguage = withoutLanguage.replace(pattern, ' ');
  // Conjunctions describe multiple possible learning locations, not a claim
  // that any one chapter teaches the entire compound knowledge point.
  const parts = withoutLanguage.split(/\s*(?:[、，,;/；]|与|以及|\band\b|\bor\b|(?<=[\u4e00-\u9fff]{2})和(?=[\u4e00-\u9fff]{2})|\s+和\s+)\s*/i).map(part => {
    let remainder = part;
    const concepts = aliases.flatMap((pattern, index) => {
      if (!matches(pattern, part)) return [];
      remainder = remainder.replace(pattern, ' ');
      return [index];
    });
    remainder = remainder.replace(generic, ' ').replace(/[的中及]/g, ' ');
    const words = remainder.match(/[a-z][a-z0-9+#]*(?:\.[a-z0-9+#]+)*|[\u4e00-\u9fff]{2,}/gi) || [];
    return { concepts, words: words.map(word => word.toLowerCase()), literal: clean(part) };
  }).filter(part => part.concepts.length || part.words.length || part.literal);
  return { languages: contexts, parts: parts.length ? parts : contexts.length ? [{ concepts: [], words: [], literal: '' }] : [] };
}

function scoreTitle(title: string, courseTitle: string, topic: Topic): number {
  if (assessment.test(title)) return 0;
  const explicit = languages.flatMap((pattern, index) => matches(pattern, title) ? [index] : []);
  if (topic.languages.length && (explicit.some(index => !topic.languages.includes(index)) || !topic.languages.every(index => matches(languages[index], `${courseTitle} ${title}`)))) return 0;
  const normalizedTitle = clean(title);
  return Math.max(0, ...topic.parts.map(part => {
    if (!part.concepts.length && !part.words.length) {
      return introduction.test(title) && !aliases.some(pattern => matches(pattern, title))
        && (topic.languages.length > 0
          ? topic.languages.every(index => matches(languages[index], title))
          : part.literal.length >= 2 && normalizedTitle.includes(part.literal)) ? 1 : 0;
    }
    if (!part.concepts.every(index => matches(aliases[index], title))) return 0;
    if (!part.words.every(word => /[\u4e00-\u9fff]/.test(word) ? normalizedTitle.includes(clean(word)) : new RegExp(`(?<![a-z0-9])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![a-z0-9])`, 'i').test(title))) return 0;
    return 3 + part.concepts.length + part.words.length + (part.literal.length >= 2 && normalizedTitle.includes(part.literal) ? 1 : 0);
  }));
}

/** Select a few evidenced learning locations, without exposing the directory or
 * upgrading the resource's topic/teaching coverage assessment. */
export function recommendChapters(item: ResourceItem, knowledgePoints: string[], limit = 2): ChapterRecommendation[] {
  const bounded = Number.isSafeInteger(limit) && limit > 0 ? Math.min(limit, 10) : 2;
  const requestedPoints = knowledgePoints.filter(point => typeof point === 'string' && point.trim());
  if (!requestedPoints.length) return [];
  const supporting = new Set(item.match.supporting_evidence_ids || []);
  const partial = item.match.topic_evidence_status === 'partial';
  const observed = new Set((item.evidence || []).filter(record => ['search', 'page', 'catalog'].includes(record.kind)).map(record => record.evidence_id));
  const supportedParts = (item.match.subtopic_coverage || []).filter(part => part.status === 'supported'
    && typeof part.text === 'string' && part.text.trim()
    && part.evidence_ids.some(id => supporting.has(id) && observed.has(id)));
  const chapterSupport = new Set(supportedParts.flatMap(part => part.evidence_ids.filter(id => supporting.has(id) && observed.has(id))));
  // A partial resource's unknown tasks must not create chapter recommendations.
  // Keep only catalog records the backend explicitly bound to a supported part;
  // page-only support leaves the learning location unconfirmed.
  const topics = (partial ? supportedParts.map(part => part.text) : requestedPoints)
    .filter(point => typeof point === 'string' && point.trim()).map(topicFor);
  if (!topics.length) return [];
  // Only explicitly matched parts participate in diversity. Course context and
  // generic introductions cannot stand in for a missing list/tuple/etc. title.
  const parts = [...new Map(topics.flatMap(topic => topic.parts.filter(part => part.concepts.length || part.words.length).map(part => {
    const key = JSON.stringify([topic.languages, [...part.concepts].sort(), [...part.words].sort()]);
    return [key, { ...topic, parts: [part] }] as [string, Topic];
  }))).entries()];
  const requestedTopics = requestedPoints.map(topicFor);
  const ranked = verifiedChapters(item).filter(chapter => {
    if (!partial) return true;
    if (!chapterSupport.has(chapter.evidenceId) || assessment.test(chapter.title)) return false;
    const explicit = languages.flatMap((pattern, index) => matches(pattern, chapter.title) ? [index] : []);
    // API-title fallback may lack literal topic words, but it must not override
    // an explicit different programming language or an assessment-only lesson.
    return requestedTopics.some(topic => !topic.languages.length || explicit.every(index => topic.languages.includes(index)));
  }).map(chapter => ({
    chapter,
    score: Math.max(partial ? 1 : 0, ...topics.map(topic => scoreTitle(chapter.title, item.resource.title || '', topic))),
    parts: parts.filter(([, topic]) => scoreTitle(chapter.title, item.resource.title || '', topic) > 0).map(([key]) => key),
  }))
    .filter(row => row.score > 0)
    .sort((a, b) => b.score - a.score || Number(supporting.has(b.chapter.evidenceId)) - Number(supporting.has(a.chapter.evidenceId)) || a.chapter.ordinal - b.chapter.ordinal);
  const selected: typeof ranked = [];
  const covered = new Set<string>();
  while (selected.length < bounded) {
    let best: typeof ranked[number] | undefined;
    let added = 0;
    for (const row of ranked) {
      if (selected.includes(row)) continue;
      const gain = row.parts.filter(part => !covered.has(part)).length;
      // ranked already supplies the established score/support/order tie break.
      if (gain > added) { best = row; added = gain; }
    }
    if (!best) break;
    selected.push(best);
    for (const part of best.parts) covered.add(part);
  }
  for (const row of ranked) {
    if (selected.length >= bounded) break;
    if (!selected.includes(row)) selected.push(row);
  }
  return selected.map(row => row.chapter);
}
