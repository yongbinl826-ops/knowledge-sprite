import { useEffect, useRef, useState, type FormEvent } from 'react';
import { BookIcon } from './Icons';
import type { Capabilities, Platform, SearchPipeline } from '../types';
import { emptyProjectInput, projectStatusNames, type ProjectInput } from '../projectTypes';
import { useProject } from '../useProject';
import { ProjectConfirmation } from './ProjectLearning';
import { ProjectVideoGallery } from './ProjectVideoGallery';
import { nativeMotionAvailable, useMotionValue } from '../motion';
import { projectSubtopicSummary } from '../projectSubtopicSummary';
import { hasProjectScopeMismatch } from '../projectTypes';
import { ProjectSearchProgress } from './SearchPipelineProgress';
import { relatedRecommendations } from '../relatedRecommendations';
import { visibleGroupItems } from '../topicEvidence';
import { externalUrl } from '../safeUrls';
import type { useDeviceProject } from '../device/useDeviceProject';
import { visibleTopicTechnology } from '../reviewedTopicTechnologies';
import { hasHelpfulVideoPolicy, helpfulVideoRecommendations } from '../helpfulVideoRecommendations';

type Stage = 1 | 2 | 3;
const inputDraftKey = 'knowledge-guide-project-input-v1';
const resultTerminalStatuses = new Set(['completed', 'partial', 'no_results', 'failed', 'cancelled', 'interrupted', 'budget_exceeded']);
const stageLabels = ['项目描述', '选择知识点', '推荐视频'];
const preparingSearchPipeline: SearchPipeline = {
  stage: 'queued', terminal: false, source_limited: false, search_requests: 0, search_budget: 0,
  candidates: 0, checking: 0, displayed: 0, filtered: 0, unknown: 0,
};
function readInputDraft(): ProjectInput {
  try {
    const draft = JSON.parse(localStorage.getItem(inputDraftKey) || 'null');
    if (draft && typeof draft.name === 'string' && typeof draft.requirements === 'string') {
      return { ...emptyProjectInput, name: draft.name.slice(0, 160), requirements: draft.requirements.slice(0, 8000),
        student_level: ['beginner', 'intermediate', 'advanced', 'any'].includes(draft.student_level) ? draft.student_level : 'any',
        language: ['zh', 'en', 'any'].includes(draft.language) ? draft.language : 'zh',
        project_context: typeof draft.project_context === 'string' ? draft.project_context.slice(0, 1000) : '',
        technical_version: typeof draft.technical_version === 'string' ? draft.technical_version.slice(0, 100) : '',
        preferred_platforms: Array.isArray(draft.preferred_platforms) ? [...new Set<Platform>(draft.preferred_platforms.filter((value: Platform) => ['bilibili', 'icourse163', 'xuetangx'].includes(value)))] : emptyProjectInput.preferred_platforms };
    }
  } catch { /* The form works with storage disabled. */ }
  return { ...emptyProjectInput };
}

type FlowProps = { capabilities: Capabilities | null; capabilityError?: string; onManual: () => void };
export function ProjectFlow(props: FlowProps) { const project = useProject(); return <ProjectFlowView {...props} project={project}/>; }
export function ProjectFlowView({ capabilities, capabilityError, onManual, project, device, storageNotice }: FlowProps & {
  project: ReturnType<typeof useProject>; device?: ReturnType<typeof useDeviceProject>; storageNotice?: string;
}) {
  const [input, setInput] = useState(() => device ? { ...emptyProjectInput, preferred_platforms: ['bilibili', 'icourse163'] as Platform[] } : readInputDraft());
  const [validation, setValidation] = useState('');
  const [screen, setScreen] = useState<Stage | null>(null);
  const [showProjects, setShowProjects] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [topic, setTopic] = useState('all');
  const [compactLayout, setCompactLayout] = useState(() => window.matchMedia('(max-width: 640px)').matches);
  const [selectedCount, setSelectedCount] = useState(0);
  const [displayedVideoCount, setDisplayedVideoCount] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [cancelledSearchKey, setCancelledSearchKey] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState(device ? '正在读取本机草稿' : '');
  const titleRef = useRef<HTMLHeadingElement>(null);
  const inputSaveRevision = useRef(0);
  const view = project.view;
  const version = view?.version || null;
  const analyzing = version?.status === 'analyzing';
  const readingDevice = !!device && project.loading;
  const unavailable = ['unconfigured', 'unavailable', 'disabled'].includes(capabilities?.project_analysis?.status || '');
  const analysisStatusMessage = capabilities?.project_analysis?.message?.replace(/^(?:项目分析不可用[：:]\s*)+/, '') || '服务端尚未配置模型。';
  const current = !version || version.version === view?.current_version;
  const inputDirty = !!version?.analysis && JSON.stringify(input) !== JSON.stringify(version.input);
  const naturalStage: Stage = version?.confirmation && version.analysis?.knowledge_points.some(point => point.selection === 'learn') ? 3 : version?.analysis ? 2 : 1;
  const targetStage = retrying ? 3 : screen && screen <= naturalStage ? screen : naturalStage;
  const stage = useMotionValue(targetStage, 'stage');
  const lastAnalyzing = useRef(analyzing);
  const analysisWaiting = analyzing || stage === 1 && targetStage > 1 && lastAnalyzing.current;
  useEffect(() => { lastAnalyzing.current = analyzing; }, [analyzing]);
  const inputKey = `${view?.project_id || ''}:${version?.version || 0}`;
  const previousStage = useRef(stage);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 640px)');
    const update = () => setCompactLayout(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    inputSaveRevision.current += 1;
    if (view) { setInput(version?.input || view.input); setDraftStatus(device ? '输入已可靠保存在本机' : ''); }
    else if (!project.loading) setInput(device?.inputDraft || (device ? { ...emptyProjectInput, preferred_platforms: ['bilibili', 'icourse163'] as Platform[] } : readInputDraft()));
    setScreen(null); setValidation(''); setTopic('all');
    // Status polling must preserve in-progress typing on the same version.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputKey, device ? project.loading : false]);
  useEffect(() => {
    if (stage !== previousStage.current) {
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      titleRef.current?.focus({ preventScroll: true });
    }
    previousStage.current = stage;
  }, [stage]);
  useEffect(() => {
    if (!device) return;
    const back = (event: Event) => { if (stage > 1) { event.preventDefault(); setScreen((stage - 1) as Stage); } };
    document.addEventListener('device-back', back); return () => document.removeEventListener('device-back', back);
  }, [device, stage]);
  const changeInput = (patch: Partial<ProjectInput>) => {
    const next = { ...input, ...patch }; setInput(next);
    if (device) {
      const revision = ++inputSaveRevision.current;
      setDraftStatus('正在保存到本机…');
      void device.saveInputDraft(next).then(() => { if (revision === inputSaveRevision.current) setDraftStatus('草稿已保存在本机'); }).catch(() => { if (revision === inputSaveRevision.current) setDraftStatus('本次输入尚未可靠保存，请检查存储后重试'); });
    } else {
      try { localStorage.setItem(inputDraftKey, JSON.stringify(next)); setDraftStatus(''); }
      catch { setDraftStatus('浏览器存储不可用，请保留当前页面'); }
    }
  };
  const startAnalysis = async (event: FormEvent) => {
    event.preventDefault();
    if (!input.name.trim() || !input.requirements.trim()) { setValidation('请填写项目名称和功能需求。'); return; }
    setValidation('');
    const next = await project.analyze(input);
    if (next) {
      setScreen(null);
      if (!device) { try { localStorage.removeItem(inputDraftKey); } catch { /* Server input remains recoverable. */ } }
    }
  };
  const retrySearch = async () => {
    if (project.busy || retrying) return;
    setCancelledSearchKey(null);
    setRetrying(true);
    try { await project.retrySearch(); }
    finally { setRetrying(false); }
  };
  const cancelSearch = async () => {
    if (project.busy) return;
    const key = inputKey;
    setCancelledSearchKey(key);
    let accepted = false;
    try { accepted = !!(await project.cancel()); }
    finally {
      if (!accepted) setCancelledSearchKey(currentKey => currentKey === key ? null : currentKey);
    }
  };
  // Retry preparation and the first results read precede the server's pipeline snapshot.
  const progressPipeline = retrying || (!view?.pipeline && version?.status === 'running')
    ? preparingSearchPipeline : view?.pipeline;
  const error = version?.error ? typeof version.error === 'string' ? version.error : version.error.message : '';
  const selected = version?.analysis?.knowledge_points.filter(point => point.selection === 'learn') || [];
  const partialScopes = capabilities?.teaching_match_enabled === false ? [] : selected
    .filter(point => topic === 'all' || topic === point.id).flatMap(point => {
      const result = view?.points?.find(row => row.project_knowledge_point_id === point.id);
      if (!result?.result || hasProjectScopeMismatch(result) || hasHelpfulVideoPolicy(result.result)) return [];
      const rows = projectSubtopicSummary(result.result, capabilities?.limits.max_results_per_point || 5);
      return rows.some(row => !row.supported) ? [{ point, rows }] : [];
    });
  const activePoints = selected.filter(point => topic === 'all' || topic === point.id);
  const noMatchedVideo = capabilities?.teaching_match_enabled !== false && activePoints.length > 0 && activePoints.every(planned => {
    const point = view?.points?.find(row => row.project_knowledge_point_id === planned.id);
    if (!point || hasProjectScopeMismatch(point) || !resultTerminalStatuses.has(point.status)) return false;
    if (point.result && hasHelpfulVideoPolicy(point.result)) return helpfulVideoRecommendations(point.result).length === 0;
    if (point.result && relatedRecommendations(point.result).length) return false;
    return !point.result || !visibleGroupItems(point.result, 'all', 'learning', point.result.section_limit || capabilities?.limits.max_results_per_point || 5)
      .some(({ item, status }) => status !== 'needs_review' && !!externalUrl(item.resource.url));
  });
  // Keep the mobile reading and tab order aligned: resources precede supporting
  // notes and recovery controls. Desktop keeps these in its existing sidebar.
  const resultDetails = stage === 3 ? <div className="project-result-details">
    {partialScopes.map(({ point, rows }) => <section key={point.id} className="project-support-summary" aria-label={`${point.name}的材料范围`}>
      <p className="project-support-title">{topic === 'all' ? point.name : '材料范围'}</p>
      <p data-support={rows.some(row => row.supported) ? 'partial' : 'unknown'}>{rows.some(row => row.supported)
        ? '部分匹配不等于单门课程完整覆盖，请核对课程内容。'
        : '当前材料的完整讲授范围尚待核对，请结合课程详情判断。'}</p>
    </section>)}
    {!progressPipeline && noMatchedVideo && <p className="project-empty-message" role="status">当前知识点暂无推荐视频。可重新检索或调整知识点。</p>}
    {!progressPipeline && project.notice && <p className="action-notice" role="status">{project.notice}</p>}
    {project.error && <div className="notice error-notice" role="alert">{project.error}<button className="text-button" onClick={project.refresh}>重新读取</button></div>}
    {error && <div className="notice error-notice" role="alert">{error}</div>}
    {version && <div className="project-search-controls">
      {!progressPipeline && <p className="field-help" role="status">{device && version.confirmation?.local_only === true ? '仅本机确认，未开始课程检索' : `视频检索：${projectStatusNames[version.status] || version.status}`}</p>}
      {current && version.status === 'running' && <button className="text-button" disabled={project.busy} onClick={() => void cancelSearch()}>取消项目检索</button>}
      {current && selected.length > 0 && ['completed', 'partial', 'failed', 'cancelled', 'interrupted', 'budget_exceeded', 'no_results', 'confirmed'].includes(version.status) && <button className="text-button" disabled={project.busy || retrying || inputDirty} onClick={() => void retrySearch()}>{device && version.confirmation?.local_only === true ? '查找视频' : '重新检索这些知识点'}</button>}
    </div>}
    {!current && view && <button className="text-button" onClick={() => project.selectProject(view.project_id, view.current_version)}>返回当前项目</button>}
    {inputDirty && <p className="notice warning-notice">需求已有未保存修改，请先返回项目描述并重新分析。</p>}
  </div> : null;
  return <>
    <a className="skip-link" href="#stage-title">跳转到主要内容</a>
    <header className="site-header">
      <div className="brand"><BookIcon/><span>项目制学习引导小精灵</span></div>
      <nav className="stage-navigation" aria-label="项目学习流程">{stageLabels.map((label, index) => {
        const number = (index + 1) as Stage;
        return <button key={label} className={stage === number ? 'current' : ''} aria-current={stage === number ? 'step' : undefined} disabled={number > naturalStage || project.busy || analyzing} onClick={() => setScreen(number)}><span className="step-dot" aria-hidden="true">{number < naturalStage ? '✓' : ''}</span><span className="step-number">0{number}</span>{label}</button>;
      })}</nav>
      <button className="projects-toggle text-button" aria-expanded={showProjects} aria-controls="project-library" onClick={() => setShowProjects(value => !value)}>我的项目 <span aria-hidden="true">{showProjects ? '−' : '↗'}</span></button>
    </header>
    {stage === 3 && progressPipeline && !progressPipeline.terminal && (retrying || version?.status !== 'cancelled') && cancelledSearchKey !== inputKey && <ProjectSearchProgress pipeline={progressPipeline} displayed={displayedVideoCount}/>}
    {showProjects && <section className="project-library" id="project-library" aria-label="我的项目">
      <div className="project-toolbar">
        <label>已保存项目<select aria-label="已保存项目" value={view?.project_id || ''} disabled={project.busy} onChange={event => project.selectProject(event.target.value)}><option value="">新项目</option>{project.projects.map(item => <option key={item.project_id} value={item.project_id}>{item.name}</option>)}</select></label>
        <button className="secondary-button" disabled={project.busy} onClick={() => { project.newProject(); changeInput({ ...emptyProjectInput, preferred_platforms: device ? ['bilibili', 'icourse163'] : emptyProjectInput.preferred_platforms }); setScreen(null); }}>新建项目</button>
        <button className="text-button" disabled={project.busy} onClick={project.refresh}>重新读取</button>
        {device && view && <button className="text-button" disabled={project.busy || !device.canRemove} onClick={() => setDeleteConfirm(true)}>删除本机项目</button>}
      </div>
      {device && deleteConfirm && <div className="notice warning-notice" role="alert"><p>删除此项目会从这台设备永久移除输入、版本和学习进度，无法恢复。</p><button className="secondary-button" disabled={project.busy} onClick={() => { void device.removeProject().then(() => setDeleteConfirm(false)); }}>确认删除本机项目</button><button className="text-button" onClick={() => setDeleteConfirm(false)}>保留项目</button></div>}
      {device && !device.canRemove && <p className="field-help">临时任务尚未结束；请先取消或重新读取最终状态后，再删除项目释放空间。</p>}
      {device && <p>项目、勾选与学习进度仅保存在这台设备。卸载或清除应用数据会丢失记录；没有账号与云同步。</p>}
    </section>}
    <main className={`stage-main stage-${stage}${nativeMotionAvailable() ? '' : ' motion-fallback'}`}>
      <aside className="stage-intro" key={`intro-${stage}`}>
        <p className="section-index">{stage === 1 ? '01 / PROJECT BRIEF' : stage === 2 ? '02 / LEARNING SCOPE' : '03 / CURATED LEARNING'}</p>
        <h1 id="stage-title" ref={titleRef} tabIndex={-1} aria-label={compactLayout ? stageLabels[stage - 1] : undefined}>{stage === 1 ? <>从一个想法，<br/>开始你的项目。</> : stage === 2 ? <>选择此刻，<br/>想学的知识。</> : <>让知识，<br/>走进你的项目。</>}</h1>
        <div className="stage-context">
        <p className="stage-description">{stage === 1 ? <>描述你想实现的功能，<br/>让学习围绕项目展开。</> : stage === 2 ? <>围绕 {input.name}，<br/>确认要学习的专业知识点。</> : <><span className="stage-project-name">{input.name}</span><span className="stage-description-copy"><br/>从相关的视频开始。</span></>}</p>
        <div className="stage-next">{stage === 1 ? <><span>下一步</span><p>梳理需要学习的知识点 <span aria-hidden="true">→</span></p></> : <button className="text-button" onClick={() => setScreen(stage === 2 ? 1 : 2)}>{stage === 2 ? '查看或修改项目描述' : '← 调整知识点'} <span aria-hidden="true">{stage === 2 ? '↗' : ''}</span></button>}</div>
        </div>
        {stage === 2 && <p className="selection-count">已选择 <strong>{selectedCount}</strong> 个知识点<span>勾选需要学习的知识点。</span></p>}
        {stage === 3 && <nav className="topic-navigation" aria-label="已选知识点"><p>已选知识点</p><button className={topic === 'all' ? 'active' : ''} aria-pressed={topic === 'all'} onClick={() => setTopic('all')}>全部</button>{selected.map(point => <button key={point.id} className={topic === point.id ? 'active' : ''} aria-label={point.name} aria-describedby={visibleTopicTechnology(point) ? `topic-context-${point.id}` : undefined} aria-pressed={topic === point.id} onClick={() => setTopic(point.id)}>{point.name}{visibleTopicTechnology(point) && <small id={`topic-context-${point.id}`}>检索语境：{visibleTopicTechnology(point)}</small>}</button>)}</nav>}
        {!compactLayout && resultDetails}
        <span className="outline-number" aria-hidden="true">0{stage}</span>
      </aside>
      <div className="stage-content" key={`content-${stage}`}>
        {stage !== 3 && project.error && <div className="notice error-notice" role="alert">{project.error}<button className="text-button" onClick={project.refresh}>重新读取</button></div>}
        {stage !== 3 && project.notice && <p className="action-notice" role="status">{project.notice}</p>}
        {stage !== 3 && project.loading && <p className="notice" role="status">正在读取保存的项目…</p>}
        {stage !== 3 && !current && view && <button className="secondary-button" onClick={() => project.selectProject(view.project_id, view.current_version)}>返回当前项目</button>}
        {stage === 1 && <div className="analysis-surface" data-analyzing={analysisWaiting}><section className="panel project-description" aria-label="项目描述" inert={analysisWaiting}><form onSubmit={event => void startAnalysis(event)}>
          <div className="field"><label htmlFor="project-name">项目名称</label><input id="project-name" autoComplete="off" value={input.name} disabled={project.busy || analyzing || !current || readingDevice} onChange={event => changeInput({ name: event.target.value })} maxLength={160} placeholder="例如：用 Python 做一个接球小游戏" required/></div>
          <div className="field"><label htmlFor="project-requirements">功能需求</label><textarea id="project-requirements" rows={7} value={input.requirements} disabled={project.busy || analyzing || !current || readingDevice} onChange={event => changeInput({ requirements: event.target.value })} maxLength={8000} placeholder={'说说它需要完成什么，例如：\n用方向键移动挡板，接住下落的小球\n记录分数，漏接后可以重新开始'} required aria-describedby="requirements-help"/><span className="field-help" id="requirements-help">直接描述功能，不需要先知道专业术语。<span>{input.requirements.length} / 8000</span></span></div>
          <div className="field"><label htmlFor="project-language">视频语言</label><select id="project-language" value={input.language} disabled={!current || analyzing || readingDevice} onChange={event => changeInput({ language: event.target.value as ProjectInput['language'] })}><option value="zh">中文</option><option value="en">英语</option><option value="any">不限</option></select></div>
          {(unavailable || capabilityError) && <div className="notice warning-notice">{unavailable ? `项目分析不可用：${analysisStatusMessage}` : capabilityError} 可继续使用“直接搜索知识点”。</div>}
          {validation && <p className="form-error" role="alert">{validation}</p>}
          {error && <div className="notice error-notice" role="alert">{error} 输入已保留，可修改后重新分析。</div>}
          <div className="form-action-row">{draftStatus && <span className="draft-status">{draftStatus}</span>}{current && <button className="primary-button" type="submit" disabled={project.busy || analyzing || readingDevice}>{analyzing ? '正在梳理知识点…' : unavailable ? '保存项目并检查分析配置' : version ? '保存需求并重新分析' : '分析项目'}<span aria-hidden="true">→</span></button>}</div>
          {device && <p className="field-help">个人项目保存在设备，仅在点击分析或查视频时发送必要内容到服务端临时处理；临时任务两小时后失效。卸载或清除应用数据会丢失本机记录。</p>}
        </form></section>
        {analysisWaiting && <div className="panel analysis-progress" role="status"><div className="breathing-dots" aria-hidden="true"><i/><i/><i/></div><strong>正在梳理项目知识点</strong>{!device && <p>提取项目涉及的专业知识点。刷新页面可恢复。</p>}{device && <button className="text-button" disabled={project.busy} onClick={() => void project.cancel()}>取消本次分析</button>}</div>}
        </div>}
        {stage === 1 && <button className="manual-entry text-button" onClick={onManual}>直接搜索知识点 <span aria-hidden="true">↗</span></button>}
        {inputDirty && stage === 2 && <p className="notice warning-notice">需求已有未保存修改，请先返回项目描述并重新分析。</p>}
        {stage === 2 && version?.analysis && view && <ProjectConfirmation key={`${view.project_id}:${version.version}`} projectId={view.project_id} version={version} current={current} busy={project.busy} inputDirty={inputDirty} capabilities={capabilities} onSelectedChange={setSelectedCount} deviceDraft={device?.editDraft} deviceMode={!!device} onDraftChange={device?.saveEditDraft} onSave={project.save} onConfirm={async (...args) => { setScreen(null); const result = await project.confirmAndSearch(...args); if (result) setScreen(null); return result; }}/>}
        {stage === 3 && version?.confirmation && <ProjectVideoGallery version={version} points={view?.points || []} capabilities={capabilities} topic={topic} pipeline={view?.pipeline} starting={project.busy && version.status === 'confirmed' && version.confirmation.local_only !== true} onDisplayedChange={setDisplayedVideoCount}/>}
      </div>
      {compactLayout && resultDetails}
    </main>
    <footer className="site-footer"><span>让学习，发生在项目里。</span>{device && <span>{storageNotice} · 无账号与云同步</span>}</footer>
  </>;
}
