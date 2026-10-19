import { useEffect, useState } from 'react';
import type { Capabilities } from '../types';
import type { ProjectAnalysis, ProjectKnowledgePoint, ProjectVersion } from '../projectTypes';

export function ProjectConfirmation({ projectId, version, current, busy, inputDirty, capabilities, onSave, onConfirm, onSelectedChange }: {
  projectId: string; version: ProjectVersion; current: boolean; busy: boolean; inputDirty: boolean; capabilities: Capabilities | null;
  onSelectedChange: (count: number) => void;
  onSave: (analysis: ProjectAnalysis) => Promise<unknown>;
  onConfirm: (analysis: ProjectAnalysis, dirty: boolean, acknowledgements: string[]) => Promise<unknown>;
}) {
  const draftKey = `knowledge-guide-project-edit-v1:${projectId}:${version.version}`;
  const [analysis, setAnalysis] = useState<ProjectAnalysis>(() => {
    const original = structuredClone(version.analysis!);
    try {
      const draft = current ? JSON.parse(sessionStorage.getItem(draftKey) || 'null') : null;
      if (Array.isArray(draft?.functions) && Array.isArray(draft?.knowledge_points) && draft.knowledge_points.every((point: ProjectKnowledgePoint) => typeof point?.id === 'string' && typeof point?.name === 'string')) return draft;
    } catch { /* The saved server version remains available. */ }
    return original;
  });
  const [error, setError] = useState('');
  const dirty = JSON.stringify(analysis) !== JSON.stringify(version.analysis);
  const readOnly = !current || busy || inputDirty;
  const learned = analysis.knowledge_points.filter(point => point.selection === 'learn');
  useEffect(() => { onSelectedChange(learned.length); }, [learned.length, onSelectedChange]);
  const updatePoint = (id: string, patch: Partial<Pick<ProjectKnowledgePoint, 'name' | 'selection' | 'learning_order'>>) => {
    setAnalysis(before => {
      // Keep original function, prerequisite and legacy extension data untouched.
      const next = { ...before, knowledge_points: before.knowledge_points.map(point => point.id === id ? { ...point, ...patch } : point) };
      try { sessionStorage.setItem(draftKey, JSON.stringify(next)); } catch { /* The user can still save explicitly. */ }
      return next;
    });
    setError('');
  };
  const batchSize = Math.max(1, Math.min(5, capabilities?.limits.max_knowledge_points || 5, capabilities?.project_search?.batch_size || 5));
  const overBudget = Math.ceil(learned.length / batchSize) > (capabilities?.project_search?.max_batches || Infinity);
  const submit = async (confirm: boolean) => {
    if (analysis.knowledge_points.some(point => !point.name.trim())) { setError('请填写知识点的专业名称。'); return; }
    if (analysis.knowledge_points.some(point => !Number.isInteger(point.learning_order) || point.learning_order < 1 || point.learning_order > 24)) { setError('顺序请输入 1–24 的整数。'); return; }
    if (overBudget) { setError('选择数量超过本次检索上限，请减少一些知识点。'); return; }
    setError('');
    const next = confirm ? await onConfirm(analysis, dirty, []) : await onSave(analysis);
    if (next) { try { sessionStorage.removeItem(draftKey); } catch { /* No draft remains. */ } }
  };
  return <section className="panel project-confirmation simple-knowledge-review" aria-labelledby="project-confirmation-title">
    <div className="section-heading"><div><h2 id="project-confirmation-title" aria-label={`确认知识点 · v${version.version}`}>选择知识点</h2><p>可修改专业名称，勾选需要查找视频的知识点。</p></div><span className="job-status">{dirty ? '有未保存修改' : version.confirmation ? '本版本已确认' : '等待确认'}</span></div>
    <div className="simple-knowledge-list" aria-label="知识点列表">{[...analysis.knowledge_points].sort((a,b) => a.learning_order - b.learning_order).map(point => <article className="simple-knowledge-point" key={point.id} data-point-id={point.id}>
      <label className="sr-only" htmlFor={`simple-name-${point.id}`}>知识点名称：{point.name || '未命名知识点'}</label><input className="simple-point-name" id={`simple-name-${point.id}`} value={point.name} maxLength={160} disabled={readOnly} placeholder="例如：pygame 事件循环" onChange={event => updatePoint(point.id,{name:event.target.value})}/>
      <label className="simple-point-selection"><input type="checkbox" checked={point.selection === 'learn'} disabled={readOnly} onChange={event => updatePoint(point.id,{selection:event.target.checked ? 'learn' : 'skip'})}/>想学习<span className="sr-only">：{point.name}</span></label>
      <label className="simple-point-order">顺序<input type="number" min={1} max={24} value={point.learning_order} disabled={readOnly} aria-label={`顺序：${point.name}`} onChange={event => updatePoint(point.id,{learning_order:Number(event.target.value)})}/></label>
    </article>)}</div>
    <p className="project-search-summary">已选择 {learned.length} 个知识点{learned.length ? '' : '；保存后不创建检索任务。'}</p>
    {overBudget && <p className="notice warning-notice">选择数量超过本次检索上限，请减少一些知识点。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {current && <div className="project-actions"><button className="secondary-button" disabled={readOnly || !dirty} onClick={() => void submit(false)}>保存修改</button><button className="primary-button" disabled={readOnly || overBudget} onClick={() => void submit(true)}>{busy ? '正在保存…' : learned.length ? '查找视频' : '保存选择'}</button></div>}
  </section>;
}
