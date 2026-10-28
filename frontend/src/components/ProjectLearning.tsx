import { useEffect, useState, type CSSProperties } from 'react';
import type { Capabilities } from '../types';
import type { ProjectAnalysis, ProjectKnowledgePoint, ProjectVersion } from '../projectTypes';
import { visibleTopicTechnology } from '../reviewedTopicTechnologies';
import { MAX_PROJECT_KNOWLEDGE_POINTS } from '../projectLimits.ts';

export function ProjectConfirmation({ projectId, version, current, busy, inputDirty, capabilities, onSave, onConfirm, onSelectedChange, deviceMode = false, deviceDraft, onDraftChange }: {
  projectId: string; version: ProjectVersion; current: boolean; busy: boolean; inputDirty: boolean; capabilities: Capabilities | null;
  onSelectedChange: (count: number) => void;
  deviceMode?: boolean; deviceDraft?: ProjectAnalysis; onDraftChange?: (analysis: ProjectAnalysis) => Promise<void>;
  onSave: (analysis: ProjectAnalysis) => Promise<unknown>;
  onConfirm: (analysis: ProjectAnalysis, dirty: boolean) => Promise<unknown>;
}) {
  const draftKey = `knowledge-guide-project-edit-v1:${projectId}:${version.version}`;
  const [analysis, setAnalysis] = useState<ProjectAnalysis>(() => {
    const original = structuredClone(deviceMode && current && deviceDraft ? deviceDraft : version.analysis!);
    if (deviceMode) return original;
    try {
      const draft = current ? JSON.parse(sessionStorage.getItem(draftKey) || 'null') : null;
      if (Array.isArray(draft?.knowledge_points) && draft.knowledge_points.every((point: ProjectKnowledgePoint) => typeof point?.id === 'string' && typeof point?.name === 'string' && typeof point?.description === 'string' && ['learn', 'mastered', 'skip'].includes(point.selection))) return draft;
    } catch { /* The saved server version remains available. */ }
    return original;
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(0);
  const [nativeEntry] = useState(() => !!document.documentElement.dataset.motionKind);
  const dirty = JSON.stringify(analysis) !== JSON.stringify(version.analysis);
  const readOnly = !current || busy || inputDirty;
  const learned = analysis.knowledge_points.filter(point => point.selection === 'learn');
  useEffect(() => { onSelectedChange(learned.length); }, [learned.length, onSelectedChange]);
  const updatePoint = (id: string, patch: Partial<Pick<ProjectKnowledgePoint, 'name' | 'selection'>>) => {
    const next = { ...analysis, knowledge_points: analysis.knowledge_points.map(point => point.id === id ? { ...point, ...patch } : point) };
    setAnalysis(next); setError('');
    if (deviceMode && onDraftChange) {
      setSaving(value => value + 1);
      void onDraftChange(next).catch(reason => setError((reason as Error).message)).finally(() => setSaving(value => value - 1));
    } else { try { sessionStorage.setItem(draftKey, JSON.stringify(next)); } catch { /* Explicit save remains available. */ } }
  };
  const helpfulPolicy = capabilities?.project_search?.recommendation_policy === 'helpful-video-v1';
  const batchSize = helpfulPolicy
    ? Math.max(1, Math.min(capabilities?.project_analysis?.max_knowledge_points || MAX_PROJECT_KNOWLEDGE_POINTS, capabilities?.project_search?.batch_size || MAX_PROJECT_KNOWLEDGE_POINTS))
    : Math.max(1, Math.min(5, capabilities?.limits.max_knowledge_points || 5, capabilities?.project_search?.batch_size || 5));
  const overBudget = Math.ceil(learned.length / batchSize) > (capabilities?.project_search?.max_batches || Infinity);
  const submit = async (confirm: boolean) => {
    if (analysis.knowledge_points.some(point => !point.name.trim())) { setError('请填写知识点的专业名称。'); return; }
    if (overBudget) { setError('选择数量超过本次检索上限，请减少一些知识点。'); return; }
    setError('');
    const next = confirm ? await onConfirm(analysis, dirty) : await onSave(analysis);
    if (next && !deviceMode) { try { sessionStorage.removeItem(draftKey); } catch { /* No draft remains. */ } }
  };
  return <section className="panel project-confirmation simple-knowledge-review" aria-labelledby="project-confirmation-title">
    <div className="section-heading"><div><h2 id="project-confirmation-title">选择知识点</h2><p>可修改专业名称，勾选需要查找视频的知识点。</p></div></div>
    <div className={`simple-knowledge-list${nativeEntry ? ' motion-native-entry' : ''}`} aria-label="知识点列表">{analysis.knowledge_points.map((point, index) => <article className="simple-knowledge-point" key={point.id} data-point-id={point.id} style={{ '--reveal-index': Math.min(index, 4) } as CSSProperties}>
      <label className="sr-only" htmlFor={`simple-name-${point.id}`}>知识点名称：{point.name || '未命名知识点'}</label><input className="simple-point-name" id={`simple-name-${point.id}`} value={point.name} maxLength={160} disabled={readOnly} placeholder="例如：pygame 事件循环" onChange={event => updatePoint(point.id,{name:event.target.value})}/>
      <label className="simple-point-selection"><input type="checkbox" checked={point.selection === 'learn'} disabled={readOnly} onChange={event => updatePoint(point.id,{selection:event.target.checked ? 'learn' : 'skip'})}/>想学习<span className="sr-only">：{point.name}</span></label>
      {analysis.analysis_format === 'concept_list_v1' && point.description.trim() && <p className="simple-point-description">{point.description}</p>}
      {visibleTopicTechnology(point) && <p className="simple-point-context">检索语境：{visibleTopicTechnology(point)}</p>}
    </article>)}</div>
    {deviceMode && <p className="field-help" role="status">{saving ? '正在保存本机勾选…' : error ? '本次修改尚未可靠保存；请检查存储后重试。' : '专业名称和勾选已保存在本机草稿。'}</p>}
    <p className="project-search-summary">已选择 {learned.length} 个知识点{learned.length ? '' : '；保存后不创建检索任务。'}</p>
    {overBudget && <p className="notice warning-notice">选择数量超过本次检索上限，请减少一些知识点。</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {current && <div className="project-actions"><button className="secondary-button" disabled={readOnly || !dirty || !!saving} onClick={() => void submit(false)}>保存修改</button><button className="primary-button" disabled={readOnly || overBudget || !!saving || !!error} onClick={() => void submit(true)}>{busy ? '正在保存…' : learned.length ? '查找视频' : '保存选择'}</button></div>}
  </section>;
}
