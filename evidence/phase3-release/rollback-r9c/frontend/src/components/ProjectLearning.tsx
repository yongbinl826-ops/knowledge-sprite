import { useEffect, useState } from 'react';
import { dateLabel } from '../api';
import type { Capabilities } from '../types';
import type { ProjectAnalysis, ProjectKnowledgePoint, ProjectVersion } from '../projectTypes';

export function skippedDependencies(analysis: ProjectAnalysis) {
  const byId = new Map(analysis.knowledge_points.map(point => [point.id, point]));
  const conflicts = new Map<string, { point: ProjectKnowledgePoint; dependents: Set<string> }>();
  for (const target of analysis.knowledge_points.filter(point => point.selection === 'learn')) {
    const seen = new Set<string>();
    const visit = (id: string) => {
      if (seen.has(id)) return;
      seen.add(id);
      const point = byId.get(id);
      if (!point) return;
      if (point.selection === 'skip') {
        const entry = conflicts.get(id) || { point, dependents: new Set<string>() };
        entry.dependents.add(target.name); conflicts.set(id, entry);
      }
      point.prerequisite_ids.forEach(visit);
    };
    target.prerequisite_ids.forEach(visit);
  }
  return [...conflicts.values()];
}

export function ProjectConfirmation({ projectId, version, current, busy, inputDirty, capabilities, onSave, onConfirm, onSelectedChange }: {
  projectId: string; version: ProjectVersion; current: boolean; busy: boolean; inputDirty: boolean; capabilities: Capabilities | null;
  onSelectedChange: (count: number) => void;
  onSave: (analysis: ProjectAnalysis) => Promise<unknown>;
  onConfirm: (analysis: ProjectAnalysis, dirty: boolean, acknowledgements: string[]) => Promise<unknown>;
}) {
  const draftKey = `knowledge-guide-project-edit-v1:${projectId}:${version.version}`;
  const [analysis, setAnalysis] = useState<ProjectAnalysis>(() => {
    let document = structuredClone(version.analysis!);
    try { const draft = current ? JSON.parse(sessionStorage.getItem(draftKey) || 'null') : null; if (draft?.knowledge_points && draft?.functions) document = draft; } catch { /* Use server version. */ }
    // Adapt legacy selections only in the editable draft. The persisted version
    // remains unchanged until the student explicitly saves or confirms it.
    return current ? { ...document, knowledge_points: document.knowledge_points.map(point => point.selection === 'mastered' ? { ...point, selection: 'skip' } : point) } : document;
  });
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [layout, setLayout] = useState<'order' | 'task'>('order');
  const dirty = JSON.stringify(analysis) !== JSON.stringify(version.analysis);
  const conflicts = skippedDependencies(analysis);
  const allAcknowledged = conflicts.every(entry => acknowledged.includes(entry.point.id));
  const readOnly = !current || busy || inputDirty;
  const learned = analysis.knowledge_points.filter(point => point.selection === 'learn');
  useEffect(() => { onSelectedChange(learned.length); }, [learned.length, onSelectedChange]);
  const batchSize = Math.max(1, Math.min(5, capabilities?.limits.max_knowledge_points || 5, capabilities?.project_search?.batch_size || 5));
  const batchCount = Math.ceil(learned.length / batchSize);
  const overBudget = batchCount > (capabilities?.project_search?.max_batches || Infinity);
  const mutate = (change: (before: ProjectAnalysis) => ProjectAnalysis) => {
    setAnalysis(before => { const next = change(before); try { sessionStorage.setItem(draftKey, JSON.stringify(next)); } catch { /* Saving on the server remains available. */ } return next; });
    setAcknowledged([]); setError('');
  };
  const updatePoint = (id: string, patch: Partial<ProjectKnowledgePoint>) => mutate(before => ({ ...before, knowledge_points: before.knowledge_points.map(point => point.id === id ? { ...point, ...patch } : point) }));
  const removePoint = (id: string) => {
    const dependents = analysis.knowledge_points.filter(point => point.prerequisite_ids.includes(id));
    if (dependents.length) { setError(`“${dependents.map(point => point.name).join('、')}”仍依赖这个知识点。请先在这些知识点的“学习目标与前置关系”中取消对应前置，再删除。`); return; }
    mutate(before => ({ ...before, knowledge_points: before.knowledge_points.filter(point => point.id !== id) }));
  };
  const addPoint = (functionId: string) => {
    if (analysis.knowledge_points.length >= (capabilities?.project_analysis?.max_knowledge_points || 24)) { setError('知识点已达到输出上限，请缩小范围或另建下一阶段项目。'); return; }
    mutate(before => ({ ...before, knowledge_points: [...before.knowledge_points, { id: `kp_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`, name: '', description: '学生添加的知识点', function_ids: [functionId], why_needed: '用于完成所关联的项目功能', learning_goal: '能够在项目中独立应用此知识点', necessity: 'required', prerequisite_ids: [], learning_order: Math.min(24, before.knowledge_points.length + 1), selection: 'learn' }] }));
  };
  const submit = async (confirm: boolean) => {
    if (analysis.knowledge_points.some(point => !point.name.trim())) { setError('请为每个知识点填写明确、适合检索的名称。'); return; }
    const invalidOrder = analysis.knowledge_points.find(point => point.prerequisite_ids.some(id => (analysis.knowledge_points.find(prior => prior.id === id)?.learning_order || 0) >= point.learning_order));
    if (invalidOrder) { setError(`“${invalidOrder.name}”的前置学习顺序必须早于它。请在“学习目标与前置关系”中调整建议学习顺序。`); return; }
    if (analysis.functions.some(task => !analysis.knowledge_points.some(point => point.function_ids.includes(task.id)) && !task.no_new_learning_reason?.trim())) { setError('没有知识点的功能需要填写“不需要新增学习的原因”。'); return; }
    if (confirm && !allAcknowledged) { setError('请先勾选所需前置知识点，或逐项确认不学习它们的影响。'); return; }
    setError('');
    const next = confirm ? await onConfirm(analysis, dirty, acknowledged) : await onSave(analysis);
    if (next) { try { sessionStorage.removeItem(draftKey); } catch { /* No draft remains. */ } }
  };
  return <section className="panel project-confirmation" aria-labelledby="project-confirmation-title">
    <div className="section-heading"><div><h2 id="project-confirmation-title" aria-label={`确认知识点 · v${version.version}`}>你的项目，需要这些知识</h2><p>按先修顺序排列；展开学习单元，了解目标与实践任务。</p></div><span className="job-status">{dirty ? '有未保存修改' : version.confirmation ? '本版本已确认' : '等待确认'}</span></div>
    <details className="analysis-suggestions"><summary>分析建议与默认假设 <span aria-hidden="true">＋</span></summary><p className="project-scope">{analysis.scope}</p>
    {analysis.learner_profile && <p className="learner-profile">{analysis.learner_profile.assumed_knowledge.join("；")}<br/>{analysis.learner_profile.adjustment_note}</p>}
    <div className="field"><label htmlFor="project-plan">建议技术方案（可修改的假设）</label><textarea id="project-plan" rows={3} value={analysis.technical_plan} disabled={readOnly} maxLength={2000} onChange={event => mutate(before => ({ ...before, technical_plan: event.target.value }))}/></div>
    {analysis.assumptions.length > 0 && <details className="project-assumptions"><summary>查看分析假设</summary><ul>{analysis.assumptions.map((value, index) => <li key={index}>{value}</li>)}</ul></details>}
    </details>
    <div className="learning-sort" role="group" aria-label="学习单元排列方式"><button aria-pressed={layout === 'order'} onClick={() => setLayout('order')}>按学习顺序</button><button aria-pressed={layout === 'task'} onClick={() => setLayout('task')}>按项目任务</button></div>
    {layout === 'order' ? <section className="ordered-units" aria-label="学习顺序">{[...analysis.knowledge_points].sort((a,b) => a.learning_order - b.learning_order).map(point => <PointEditor key={point.id} point={point} context="ordered" analysis={analysis} readOnly={readOnly} onChange={patch => updatePoint(point.id, patch)} onDelete={() => removePoint(point.id)}/>)}<p className="field-help">需要新增单元或查看功能覆盖？切换到“按项目任务”。</p></section> : analysis.functions.map(task => {
      const points = analysis.knowledge_points.filter(point => (point.function_ids[0] === task.id)).sort((a, b) => a.learning_order - b.learning_order);
      return <section className="project-function" key={task.id} aria-label={`功能：${task.name}`}><div className="group-heading"><h3>{task.name}</h3><span>{points.length} 个学习单元</span></div><details className="task-completion"><summary>项目子任务与完成标准</summary><p>{task.original_requirement}</p><p>{task.acceptance_criteria}</p></details>
        {points.map(point => <PointEditor key={point.id} point={point} context={task.id} analysis={analysis} readOnly={readOnly} onChange={patch => updatePoint(point.id, patch)} onDelete={() => removePoint(point.id)}/>)}
        {!analysis.knowledge_points.some(point => point.function_ids.includes(task.id)) && <div className="field"><label htmlFor={`no-learning-${task.id}`}>不需要新增学习的原因</label><input id={`no-learning-${task.id}`} value={task.no_new_learning_reason || ''} disabled={readOnly} maxLength={500} onChange={event => mutate(before => ({ ...before, functions: before.functions.map(item => item.id === task.id ? { ...item, no_new_learning_reason: event.target.value } : item) }))}/></div>}
        <button type="button" className="text-button" disabled={readOnly} onClick={() => addPoint(task.id)}>＋ 为“{task.name}”添加知识点</button>
      </section>;
    })}
    {layout === 'task' && analysis.knowledge_points.some(point => !point.function_ids.length) && <section className="project-function"><h3>公共前置知识</h3>{analysis.knowledge_points.filter(point => !point.function_ids.length).map(point => <PointEditor key={point.id} point={point} context="prerequisite" analysis={analysis} readOnly={readOnly} onChange={patch => updatePoint(point.id, patch)} onDelete={() => removePoint(point.id)}/>)}</section>}
    {conflicts.length > 0 && <section className="notice warning-notice" aria-label="前置知识冲突"><strong>已勾选的知识点依赖尚未勾选的前置知识</strong><p>可以勾选前置知识点，也可以了解影响后继续当前选择。</p>{conflicts.map(entry => <label key={entry.point.id} className="prerequisite-ack"><input type="checkbox" disabled={readOnly} checked={acknowledged.includes(entry.point.id)} onChange={event => setAcknowledged(before => event.target.checked ? [...before, entry.point.id] : before.filter(id => id !== entry.point.id))}/><span>我了解未勾选“{entry.point.name}”可能影响“{[...entry.dependents].join('、')}”的学习，仍继续。</span></label>)}</section>}
    {overBudget && <div className="notice warning-notice">已勾选 {learned.length} 个知识点，需要 {batchCount} 批，超过项目 {capabilities?.project_search?.max_batches} 批上限。已勾选知识点全部保留，请调整选择或分阶段执行。</div>}
    <p className="project-search-summary">已勾选 {learned.length} 项 · 未勾选 {analysis.knowledge_points.length - learned.length} 项{learned.length > 0 ? ` · 最多每批 ${batchSize} 项，预计 ${batchCount} 批` : ' · 只保存，不创建空检索任务'}</p>
    {dirty && <p className="field-help">修改会保存为新版本并重新确认；原版本的检索和结果继续保留。</p>}
    {version.status === 'running' && <p className="field-help">本版本正在检索。修改将创建新版本，原版本的检索与结果继续保留。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {current && <div className="project-actions"><button className="secondary-button" disabled={readOnly || !dirty} onClick={() => void submit(false)}>保存修改，稍后确认</button><button className="primary-button" disabled={readOnly || !allAcknowledged || overBudget} onClick={() => void submit(true)}>{busy ? '正在保存…' : learned.length ? '查找推荐视频' : '保存选择'}</button></div>}
    <p className="field-help">分析模型：{version.model || 'unknown'} · 提示词：{version.prompt_version || 'unknown'} · {dateLabel(version.created_at)}</p>
  </section>;
}

function PointEditor({ point, context, analysis, readOnly, onChange, onDelete }: { point: ProjectKnowledgePoint; context: string; analysis: ProjectAnalysis; readOnly: boolean; onChange: (patch: Partial<ProjectKnowledgePoint>) => void; onDelete: () => void }) {
  const id = `${context}-${point.id}`;
  return <article className="project-point" data-point-id={point.id}>
    <span className="point-order" aria-hidden="true">{String(point.learning_order).padStart(2, "0")}</span><div className="point-title-line"><label className="sr-only" htmlFor={`name-${id}`}>知识点名称：{point.name || '新增知识点'}</label><input id={`name-${id}`} value={point.name} disabled={readOnly} maxLength={160} placeholder="填写具体、适合检索的知识点" onChange={event => onChange({ name: event.target.value })}/><span className="job-status">{point.necessity === 'required' ? '必需' : '拓展'}</span><button className="text-button" disabled={readOnly} onClick={onDelete} aria-label={`删除知识点：${point.name || '新增知识点'}`}>删除</button></div>
    <div className="point-choices" role="group" aria-label={`${point.name || '新增知识点'}的学习选择`}><label><input type="checkbox" checked={point.selection === 'learn'} disabled={readOnly} onChange={event => onChange({ selection: event.target.checked ? 'learn' : 'skip' })}/>想学习</label></div>
    <p className="point-task">用于 {point.function_ids.length ? point.function_ids.map(functionId => analysis.functions.find(task => task.id === functionId)?.name).filter(Boolean).join("、") : "后续单元的必要准备"}</p><p className="point-description">{point.project_task || point.description}</p><p className="point-goal">{point.learning_goal}</p>
    <details className="point-details"><summary>学习目标与前置关系 · 建议顺序 {point.learning_order}{point.function_ids.length > 1 ? ` · 共享于 ${point.function_ids.length} 个功能` : ''}</summary>
      <div className="learning-detail-copy"><p><strong>为什么学：</strong>{point.why_needed}</p>{point.concepts?.length ? <p><strong>概念与技能：</strong>{point.concepts.join(' · ')}</p> : null}<p><strong>学会后能做：</strong>{point.practice_check || point.learning_goal}</p><p><strong>必要先修：</strong>{point.prerequisite_ids.length ? point.prerequisite_ids.map(prior => analysis.knowledge_points.find(item => item.id === prior)?.name || prior).join('、') : '无额外先修，可从这里开始'}</p>{point.function_ids.length > 1 && <p><strong>同时用于：</strong>{point.function_ids.map(functionId => analysis.functions.find(task => task.id === functionId)?.name).filter(Boolean).join('、')}</p>}</div>
      <div className="field"><label htmlFor={`technology-${id}`}>本单元使用的工具或技术</label><input id={`technology-${id}`} maxLength={80} value={point.technology || ''} disabled={readOnly} placeholder="例如 pygame、pandas、Arduino" onChange={event => onChange({ technology: event.target.value })}/><p className="field-help">用于寻找同一种技术的教程；通用概念可以留空。</p></div>
      <div className="field"><label htmlFor={`goal-${id}`}>学习到什么程度</label><textarea id={`goal-${id}`} rows={2} maxLength={800} value={point.learning_goal} disabled={readOnly} onChange={event => onChange({ learning_goal: event.target.value })}/></div>
      <div className="field-pair"><div className="field"><label htmlFor={`order-${id}`}>建议学习顺序</label><input id={`order-${id}`} type="number" min={1} max={24} value={point.learning_order} disabled={readOnly} onChange={event => onChange({ learning_order: Number(event.target.value) })}/></div><div className="field"><label htmlFor={`necessity-${id}`}>学习属性</label><select id={`necessity-${id}`} value={point.necessity} disabled={readOnly} onChange={event => onChange({ necessity: event.target.value as ProjectKnowledgePoint['necessity'] })}><option value="required">必需</option><option value="extension">拓展</option></select></div></div>
      <fieldset className="point-relations" disabled={readOnly}><legend>前置知识点（可调整，顺序需早于当前知识点）</legend>{analysis.knowledge_points.filter(item => item.id !== point.id).map(item => <label key={item.id}><input type="checkbox" checked={point.prerequisite_ids.includes(item.id)} onChange={event => onChange({ prerequisite_ids: event.target.checked ? [...point.prerequisite_ids, item.id] : point.prerequisite_ids.filter(value => value !== item.id) })}/>{item.name || '未命名知识点'}</label>)}{analysis.knowledge_points.length < 2 && <p>没有其他前置知识点。</p>}</fieldset>
      <fieldset className="point-relations" disabled={readOnly}><legend>用于哪些功能</legend>{analysis.functions.map(task => <label key={task.id}><input type="checkbox" checked={point.function_ids.includes(task.id)} onChange={event => onChange({ function_ids: event.target.checked ? [...point.function_ids, task.id] : point.function_ids.filter(value => value !== task.id) })}/>{task.name}</label>)}</fieldset>
    </details>
  </article>;
}
