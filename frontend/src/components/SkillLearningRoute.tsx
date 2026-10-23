import { useEffect, useState, type ReactNode } from 'react';
import { externalUrl } from '../safeUrls';
import { learningEvidenceTexts, legacyLearningClues, skillLearningRows, transferableSkills, type SkillSource } from '../learningEvidence';
import type { ProjectKnowledgePoint } from '../projectTypes';
import type { VisibleItem } from '../topicEvidence';
import type { ResultGroup } from '../types';

const basisNames = { title: '本课标题明确', description: '简介有依据', catalog: '目录有依据', lesson_notes: '同课正文有依据' };

function SourceDetails({ sources }: { sources: SkillSource[] }) {
  return <details className="skill-source-details"><summary>查看课程依据 <span>（{sources.length}）</span></summary><ul>{sources.map(source => {
    const href = externalUrl(source.item.resource.url);
    return <li key={`${source.item.resource.resource_id}:${source.evidence.evidence_id}`}><span className={`skill-evidence-kind basis-${source.basis}`}>{basisNames[source.basis]}</span>
      {href ? <a href={href} target="_blank" rel="noopener noreferrer">{source.item.resource.title}<span className="sr-only">（在新窗口打开）</span></a> : <strong>{source.item.resource.title}</strong>}
      <blockquote>{source.quote}</blockquote></li>;
  })}</ul></details>;
}

export function SkillLearningRoute({ planned, result, rows, filtered, searching, legacy }: {
  planned: ProjectKnowledgePoint; result: ResultGroup | null | undefined; rows: VisibleItem[]; filtered: boolean; searching: boolean;
  legacy: ReactNode;
}) {
  const evidenceKey = JSON.stringify(learningEvidenceTexts(rows));
  const [digestState, setDigestState] = useState(() => ({ key: '', values: new Map<string, string>() }));
  useEffect(() => {
    const texts = JSON.parse(evidenceKey) as string[];
    let stale = false;
    void Promise.all(texts.map(async text => {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [text, [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')] as const;
    })).then(values => { if (!stale) setDigestState({ key: evidenceKey, values: new Map(values) }); })
      .catch(() => { if (!stale) setDigestState({ key: evidenceKey, values: new Map() }); });
    return () => { stale = true; };
  }, [evidenceKey]);
  const checking = evidenceKey !== '[]' && digestState.key !== evidenceKey;
  const skills = transferableSkills(planned);
  const assessed = skillLearningRows(planned, result, rows, digestState.key === evidenceKey ? digestState.values : new Map());
  const content = assessed.filter(row => row.content.length);
  const titles = assessed.filter(row => !row.content.length && row.titles.length);
  const clues = skills.length ? [] : legacyLearningClues(result, rows);
  const first = content.flatMap(row => row.content).find(source => externalUrl(source.item.resource.url))
    || titles.flatMap(row => row.titles).find(source => externalUrl(source.item.resource.url)) || clues.map(row => row.source).find(source => externalUrl(source.item.resource.url));
  const firstUrl = first && externalUrl(first.item.resource.url);
  const next = content.length ? '先学习已有内容依据的技能，再按项目要求试做。其他技能仍可补充资料；项目参数与边界需自己核对。'
    : searching ? '检索仍在进行，学习目标与项目练习已保留，请等待材料返回。'
    : titles.length || clues.length ? '已有入门材料的标题线索。先到原平台核对教学范围；精确参数和项目行为仍需补学或实践。'
    : filtered ? '当前平台尚无可确认的技能依据，可切换到全部平台核对其他课程。'
    : rows.length ? '已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。'
    : '尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。';
  return <aside className="unit-learning-route" aria-label={`${planned.name}的学习路线`}>
    <div className="learning-route-heading"><h5>从学会技能，到完成项目</h5><span role="status">{checking ? '正在核对课程依据…' : content.length ? `${content.length} 项技能有内容依据` : titles.length ? `${titles.length} 项本课标题明确` : clues.length ? `${clues.length} 条局部入门线索` : '教学范围待核对'}</span></div>
    <div className="learning-route-axes">
      <section className="learning-skill-axis" aria-label="先学这些技能"><div className="learning-axis-title"><span aria-hidden="true">01</span><h6>先学这些技能</h6></div>
        <p className="learning-axis-intro">学习可迁移的方法；教程不必使用同款项目。</p>
        {skills.length ? <ul className="transferable-skills">{assessed.map(row => <li key={row.id} data-skill-id={row.id} data-skill-state={row.content.length ? 'content' : row.titles.length ? 'title' : 'unknown'}>
          <div className="skill-row-heading"><strong>{row.text}</strong><span className={`skill-support-state ${row.content.length ? 'content' : row.titles.length ? 'title' : 'unknown'}`}>{row.content.length ? '内容有依据' : row.titles.length ? '本课标题明确' : '待补充材料'}</span></div>
          {row.content.length ? <p className="skill-scope-note">简介、目录或同课正文支持这项技能；仍需核对深度并自己练习。</p> : row.titles.length ? <p className="skill-scope-note">来源标题明确提到这项技能；尚未确认具体教学、参数和项目应用。</p> : <p className="skill-scope-note">当前材料还没有可确认的本课教学依据。</p>}
          {(row.content.length || row.titles.length) ? <SourceDetails sources={[...row.content, ...row.titles]}/> : null}
        </li>)}</ul> : <p className="legacy-skills-note">此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。</p>}
        {clues.length ? <div className="legacy-learning-clues"><h6>现有材料的局部入门线索</h6><ul>{clues.map(clue => <li key={`${clue.source.item.resource.resource_id}:${clue.text}`}><strong>{clue.text}</strong><p>本课标题明确提到这一用法；不代表精确参数或项目行为已覆盖。</p><SourceDetails sources={[clue.source]}/></li>)}</ul></div> : null}
      </section>
      <section className="project-practice-axis" aria-label="带回项目练习"><div className="learning-axis-title"><span aria-hidden="true">02</span><h6>带回项目练习</h6><span className="practice-state">待自己实践</span></div>
        <p className="learning-axis-intro">把技能用于自己的项目。课程匹配不会自动完成这些要求。</p>
        <div className="project-practice-task"><strong>项目子任务</strong><p>{planned.project_task || planned.description}</p></div>
        {planned.concepts?.length ? <div className="project-practice-concepts"><strong>参数与应用检查</strong><ul>{planned.concepts.map((text, index) => <li key={index}>{text}</li>)}</ul></div> : null}
        {(planned.practice_check || planned.learning_goal) && <div className="project-practice-check"><strong>试做后这样检查</strong><p>{planned.practice_check || planned.learning_goal}</p></div>}
      </section>
    </div>
    <div className="learning-route-next"><strong>下一步</strong><p>{next}</p>{firstUrl && <a href={firstUrl} target="_blank" rel="noopener noreferrer">{content.length ? '从这门课开始' : '核对这门入门课'} <span aria-hidden="true">↗</span><span className="sr-only">：{first.item.resource.title}（在新窗口打开）</span></a>}</div>
    <p className="learning-route-disclaimer">{result?.learning_coverage?.disclaimer || '课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。'}</p>
    {legacy}
  </aside>;
}
