import { useEffect, useState } from 'react';
import { platformNames } from '../api';
import { relatedTopicPointers, topicPointerEvidenceTexts } from '../topicPointers';
import type { ProjectKnowledgePoint } from '../projectTypes';
import type { ResultGroup } from '../types';

export function RelatedTopicPointers({ planned, result, platform, hasMainRecommendations }: { planned: ProjectKnowledgePoint; result: ResultGroup | null | undefined; platform: string; hasMainRecommendations: boolean }) {
  const evidenceKey = JSON.stringify(topicPointerEvidenceTexts(result));
  const [digests, setDigests] = useState(() => ({ key: '', values: new Map<string, string>() }));
  useEffect(() => {
    let stale = false;
    void Promise.all((JSON.parse(evidenceKey) as string[]).map(async text => {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [text, [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')] as const;
    })).then(values => { if (!stale) setDigests({ key: evidenceKey, values: new Map(values) }); })
      .catch(() => { if (!stale) setDigests({ key: evidenceKey, values: new Map() }); });
    return () => { stale = true; };
  }, [evidenceKey]);
  const pointers = relatedTopicPointers(planned, result, platform, digests.key === evidenceKey ? digests.values : new Map());
  if (!pointers.length) return null;
  return <details className="related-topic-pointers" open={!hasMainRecommendations}><summary>相关课题线索 · 尚未证实讲授完整技能 <span>（{pointers.length}）</span></summary>
    <p>章节题目只说明相关主题，具体方法和教学深度仍需核对。</p>
    <ul>{pointers.map(({ resource, pointer, targetUrl }) => <li key={`${resource.resource_id}:${pointer.skill_id}:${pointer.evidence_id}`}>
      <p className="topic-pointer-goal"><strong>学习目标</strong>{pointer.skill}</p>
      <p className="topic-pointer-label">实际目录原题</p><blockquote>{pointer.quote}</blockquote>
      <p className="topic-pointer-source">{resource.title} · {platformNames[resource.platform] || resource.platform}</p>
      <div className="topic-pointer-missing"><strong>仍需核对</strong><p>本章是否讲授上述完整技能，仍需到平台核对。</p></div>
      <a href={targetUrl} target="_blank" rel="noopener noreferrer">到平台核对这节课 <span aria-hidden="true">↗</span><span className="sr-only">：{pointer.quote}（在新窗口打开）</span></a>
      <p className="topic-pointer-limit">授课深度、语言与访问条件仍以原平台为准。核对后再决定是否学习，并回到项目中练习。</p>
    </li>)}</ul>
  </details>;
}
