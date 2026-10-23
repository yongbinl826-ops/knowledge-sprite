import { externalUrl } from '../safeUrls';
import { collectionCoverageRows, type VisibleItem } from '../topicEvidence';
import type { ResultGroup } from '../types';
import type { ProjectKnowledgePoint } from '../projectTypes';
import { useEffect, useState } from 'react';
import { groupCoverageRows } from '../coverageDisplay';
import { contentEvidence, twtLesson, twtSummaryLimit } from '../contentEvidence';

export function LegacyLearningCoverage({ planned, result, rows, filtered, searching }: {
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
  return <aside className="unit-coverage" aria-label={`${planned.name}的原项目要求来源核对`}>
    <div className="unit-coverage-heading"><h5>原项目要求来源核对</h5><span role="status">{checking ? '正在核对内容依据…' : parts.length ? `${supported.length} / ${parts.length} 项有内容依据` : '子技能覆盖待确认'}</span></div>
    {parts.length ? <div className="unit-coverage-columns">
      <div className="unit-coverage-supported"><h6>已有来源依据</h6>{supported.length ? <ul>{supported.map(({ key, text, memberIds, sources }) => <li key={key} data-requirement-ids={JSON.stringify(memberIds)}><span>{text}</span><small>{sources.length} 个当前视频有正文或目录依据</small></li>)}</ul> : <p>这些原项目要求尚无足够的本课正文或目录依据；请结合主路线区分补学与实践。</p>}</div>
      <div className="unit-coverage-missing"><h6>原要求仍待核对</h6>{missing.length ? <ul>{missing.map(({ key, text, memberIds }) => <li key={key} data-requirement-ids={JSON.stringify(memberIds)}>{text}</li>)}</ul> : <p>已列子技能均找到内容依据，仍需核对深度与完整性。</p>}</div>
    </div> : <p className="unit-coverage-unknown">现有信息尚不足以逐项确认教学内容。{unchecked.length ? `学习时请核对：${unchecked.join('、')}。` : planned.learning_goal ? `请对照学习目标「${planned.learning_goal}」核对视频简介或目录。` : '请结合知识点说明核对视频简介或目录。'}</p>}
    <div className="unit-coverage-next"><strong>如何使用这份明细</strong><p>这里保留旧口径的来源逐项核对。参数教学仍需证据，项目应用则需要自己实践；两者不能自动相互代替。</p>
      {firstUrl && <a href={firstUrl} target="_blank" rel="noopener noreferrer">查看已有要求依据 <span aria-hidden="true">↗</span><span className="sr-only">：{first.item.resource.title}（在新窗口打开）</span></a>}
    </div>
    {practice && <p className="unit-coverage-practice"><strong>项目练习</strong><span>{practice}</span></p>}
    <p className="unit-coverage-note">仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。</p>
  </aside>;
}
