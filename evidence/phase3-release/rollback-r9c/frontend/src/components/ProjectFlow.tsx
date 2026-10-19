import { useEffect, useRef, useState, type FormEvent } from 'react';
import { BookIcon } from './Icons';
import { platformNames } from '../api';
import type { Capabilities, Platform } from '../types';
import { emptyProjectInput, projectStatusNames, type ProjectInput } from '../projectTypes';
import { useProject } from '../useProject';
import { ProjectConfirmation } from './ProjectLearning';
import { ProjectResults } from './ProjectVideos';

type Stage = 1 | 2 | 3;
const inputDraftKey = 'knowledge-guide-project-input-v1';
const stageLabels = ['项目描述', '选择知识点', '推荐视频'];
function readInputDraft(): ProjectInput {
  try {
    const draft = JSON.parse(localStorage.getItem(inputDraftKey) || 'null');
    if (draft && typeof draft.name === 'string' && typeof draft.requirements === 'string') {
      return { ...emptyProjectInput, name: draft.name.slice(0, 160), requirements: draft.requirements.slice(0, 8000),
        student_level: ['beginner', 'intermediate', 'advanced', 'any'].includes(draft.student_level) ? draft.student_level : 'beginner',
        language: ['zh', 'en', 'any'].includes(draft.language) ? draft.language : 'zh',
        project_context: typeof draft.project_context === 'string' ? draft.project_context.slice(0, 1000) : '',
        technical_version: typeof draft.technical_version === 'string' ? draft.technical_version.slice(0, 100) : '',
        preferred_platforms: Array.isArray(draft.preferred_platforms) ? [...new Set<Platform>(draft.preferred_platforms.filter((value: Platform) => ['bilibili', 'icourse163', 'xuetangx'].includes(value)))] : emptyProjectInput.preferred_platforms };
    }
  } catch { /* The form works with storage disabled. */ }
  return { ...emptyProjectInput };
}

export function ProjectFlow({ capabilities, capabilityError, onManual }: { capabilities: Capabilities | null; capabilityError?: string; onManual: () => void }) {
  const project = useProject();
  const [input, setInput] = useState(readInputDraft);
  const [validation, setValidation] = useState('');
  const [screen, setScreen] = useState<Stage | null>(null);
  const [showProjects, setShowProjects] = useState(false);
  const [topic, setTopic] = useState('all');
  const [selectedCount, setSelectedCount] = useState(0);
  const [draftStatus, setDraftStatus] = useState('草稿保存在此浏览器');
  const titleRef = useRef<HTMLHeadingElement>(null);
  const view = project.view;
  const version = view?.version || null;
  const analyzing = version?.status === 'analyzing';
  const unavailable = ['unconfigured', 'unavailable', 'disabled'].includes(capabilities?.project_analysis?.status || '');
  const current = !version || version.version === view?.current_version;
  const inputDirty = !!version?.analysis && JSON.stringify(input) !== JSON.stringify(version.input);
  const naturalStage: Stage = version?.confirmation && version.analysis?.knowledge_points.some(point => point.selection === 'learn') ? 3 : version?.analysis ? 2 : 1;
  const stage = screen && screen <= naturalStage ? screen : naturalStage;
  const inputKey = `${view?.project_id || ''}:${version?.version || 0}`;
  const previousStage = useRef(stage);
  useEffect(() => {
    if (view) { setInput(version?.input || view.input); setDraftStatus('需求已保存至本机服务'); }
    else if (!project.loading) setInput(readInputDraft());
    setScreen(null); setValidation(''); setTopic('all');
    // Status polling must preserve in-progress typing on the same version.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputKey]);
  useEffect(() => {
    if (stage !== previousStage.current) {
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      titleRef.current?.focus({ preventScroll: true });
    }
    previousStage.current = stage;
  }, [stage]);
  const changeInput = (patch: Partial<ProjectInput>) => {
    setInput(previous => {
      const next = { ...previous, ...patch };
      try { localStorage.setItem(inputDraftKey, JSON.stringify(next)); setDraftStatus('草稿已自动保存'); }
      catch { setDraftStatus('浏览器存储不可用，请保留当前页面'); }
      return next;
    });
  };
  const startAnalysis = async (event: FormEvent) => {
    event.preventDefault();
    if (!input.name.trim() || !input.requirements.trim()) { setValidation('请填写项目名称和功能需求。'); return; }
    setValidation('');
    const next = await project.analyze(input);
    if (next) {
      setScreen(null);
      try { localStorage.removeItem(inputDraftKey); } catch { /* Server input remains recoverable. */ }
    }
  };
  const error = version?.error ? typeof version.error === 'string' ? version.error : version.error.message : '';
  const selected = version?.analysis?.knowledge_points.filter(point => point.selection === 'learn') || [];
  return <>
    <a className="skip-link" href="#stage-title">跳转到主要内容</a>
    <header className="site-header">
      <div className="brand"><BookIcon/><span>项目制知识引导小精灵</span></div>
      <nav className="stage-navigation" aria-label="项目学习流程">{stageLabels.map((label, index) => {
        const number = (index + 1) as Stage;
        return <button key={label} className={stage === number ? 'current' : ''} aria-current={stage === number ? 'step' : undefined} disabled={number > naturalStage || project.busy || analyzing} onClick={() => setScreen(number)}><span className="step-dot" aria-hidden="true">{number < naturalStage ? '✓' : ''}</span><span className="step-number">0{number}</span>{label}</button>;
      })}</nav>
      <button className="projects-toggle text-button" aria-expanded={showProjects} aria-controls="project-library" onClick={() => setShowProjects(value => !value)}>我的项目 <span aria-hidden="true">{showProjects ? '−' : '↗'}</span></button>
    </header>
    {showProjects && <section className="project-library" id="project-library" aria-label="我的项目">
      <div className="project-toolbar">
        <label>已保存项目<select aria-label="已保存项目" value={view?.project_id || ''} disabled={project.busy} onChange={event => project.selectProject(event.target.value)}><option value="">新项目</option>{project.projects.map(item => <option key={item.project_id} value={item.project_id}>{item.name}</option>)}</select></label>
        {view && <label>查看版本<select aria-label="查看版本" value={version?.version || 0} disabled={project.busy} onChange={event => project.selectProject(view.project_id, Number(event.target.value))}><option value={0} disabled>尚无分析</option>{view.versions.map(item => <option key={item.version} value={item.version}>v{item.version} · {projectStatusNames[item.status] || item.status}</option>)}</select></label>}
        <button className="secondary-button" disabled={project.busy} onClick={() => { project.newProject(); changeInput({ ...emptyProjectInput }); setScreen(null); }}>新建项目</button>
        <button className="text-button" disabled={project.busy} onClick={project.refresh}>重新读取</button>
      </div>
      <p>历史版本保留原始需求与结果。当前服务为单用户工作空间，请勿输入敏感个人信息。</p>
    </section>}
    <main className={`stage-main stage-${stage}`}>
      <aside className="stage-intro">
        <p className="section-index">{stage === 1 ? '01 / PROJECT BRIEF' : stage === 2 ? '02 / LEARNING SCOPE' : '03 / CURATED LEARNING'}</p>
        <h1 id="stage-title" ref={titleRef} tabIndex={-1}>{stage === 1 ? <>从一个想法，<br/>开始你的项目。</> : stage === 2 ? <>选择此刻，<br/>想学的知识。</> : <>让知识，<br/>走进你的项目。</>}</h1>
        <p className="stage-description">{stage === 1 ? <>描述你想实现的功能，<br/>让学习围绕项目展开。</> : stage === 2 ? <>围绕 {input.name}，<br/>选择适合你的学习单元。</> : <>{input.name}<br/>从相关的视频与章节开始。</>}</p>
        <div className="stage-next">{stage === 1 ? <><span>下一步</span><p>梳理需要学习的知识点 <span aria-hidden="true">→</span></p></> : <button className="text-button" onClick={() => setScreen(stage === 2 ? 1 : 2)}>{stage === 2 ? '查看或修改项目描述' : '← 调整知识点'} <span aria-hidden="true">{stage === 2 ? '↗' : ''}</span></button>}</div>
        {stage === 2 && <p className="selection-count">已选择 <strong>{selectedCount}</strong> 个学习单元<span>建议按先修顺序学习，可自由调整。</span></p>}
        {stage === 3 && <nav className="topic-navigation" aria-label="已选知识点"><p>已选知识点</p><button className={topic === 'all' ? 'active' : ''} aria-pressed={topic === 'all'} onClick={() => setTopic('all')}>全部</button>{selected.map(point => <button key={point.id} className={topic === point.id ? 'active' : ''} aria-pressed={topic === point.id} onClick={() => setTopic(point.id)}>{point.name}</button>)}</nav>}
        <span className="outline-number" aria-hidden="true">0{stage}</span>
      </aside>
      <div className="stage-content">
        {project.error && <div className="notice error-notice" role="alert">{project.error}<button className="text-button" onClick={project.refresh}>重新读取</button></div>}
        {project.notice && <p className="action-notice" role="status">{project.notice}</p>}
        {project.loading && <p className="notice" role="status">正在读取保存的项目与版本…</p>}
        {version && <p className="project-version-label">{version.input.name} · v{version.version} · {projectStatusNames[version.status] || version.status} {!current && '（历史版本，仅查看）'}</p>}
        {!current && view && <button className="secondary-button" onClick={() => project.selectProject(view.project_id, view.current_version)}>返回最新版本</button>}
        {stage === 1 && <section className="panel project-description" aria-label="项目描述"><form onSubmit={event => void startAnalysis(event)}>
          <div className="field"><label htmlFor="project-name">项目名称</label><input id="project-name" autoComplete="off" value={input.name} disabled={project.busy || analyzing || !current} onChange={event => changeInput({ name: event.target.value })} maxLength={160} placeholder="例如：用 Python 做一个接球小游戏" required/></div>
          <div className="field"><label htmlFor="project-requirements">功能需求</label><textarea id="project-requirements" rows={7} value={input.requirements} disabled={project.busy || analyzing || !current} onChange={event => changeInput({ requirements: event.target.value })} maxLength={8000} placeholder={'说说它需要完成什么，例如：\n用方向键移动挡板，接住下落的小球\n记录分数，漏接后可以重新开始'} required aria-describedby="requirements-help"/><span className="field-help" id="requirements-help">直接描述功能，不需要先知道专业术语。<span>{input.requirements.length} / 8000</span></span></div>
          <details className="search-options"><summary>学习起点、语言与平台偏好 <span aria-hidden="true">＋</span></summary><div className="search-options-content">
            <div className="field-pair"><div className="field"><label htmlFor="project-level">我的学习起点</label><select id="project-level" value={input.student_level} disabled={!current || analyzing} onChange={event => changeInput({ student_level: event.target.value as ProjectInput['student_level'] })}><option value="beginner">初学者 · 从必要的基础开始</option><option value="intermediate">有基础 · 侧重项目应用</option><option value="advanced">进阶 · 深入实现与优化</option><option value="any">暂不确定</option></select></div><div className="field"><label htmlFor="project-language">视频语言</label><select id="project-language" value={input.language} disabled={!current || analyzing} onChange={event => changeInput({ language: event.target.value as ProjectInput['language'] })}><option value="zh">中文</option><option value="en">英语</option><option value="any">不限</option></select></div></div>
            <div className="field"><label htmlFor="project-background">我已经会什么（选填）</label><textarea id="project-background" rows={2} value={input.project_context} maxLength={1000} onChange={event => changeInput({ project_context: event.target.value })} disabled={!current || analyzing} placeholder="例如：学过 Python 循环和函数，第一次接触图形游戏。"/></div>
            <fieldset className="platform-choices" disabled={!current || analyzing}><legend>优先搜索的平台</legend><div>{(['bilibili', 'icourse163', 'xuetangx'] as Platform[]).map(platform => <label key={platform} className="platform-choice"><input type="checkbox" checked={input.preferred_platforms.includes(platform)} onChange={() => changeInput({ preferred_platforms: input.preferred_platforms.includes(platform) ? input.preferred_platforms.filter(value => value !== platform) : [...input.preferred_platforms, platform] })}/>{platformNames[platform]}</label>)}</div></fieldset>
          </div></details>
          <p className="default-assumption">{input.student_level === 'beginner' ? '先按初学者规划；有基础可在上方调整。' : input.student_level === 'intermediate' ? '按有基础的学习者规划，侧重项目应用。' : input.student_level === 'advanced' ? '按进阶学习者规划，侧重实现与优化。' : '起点暂不确定，将明确给出必要的学习假设。'}</p>
          {(unavailable || capabilityError) && <div className="notice warning-notice">{unavailable ? `项目分析不可用：${capabilities?.project_analysis?.message || '服务端尚未配置模型。'}` : capabilityError} 可继续使用“直接搜索知识点”。</div>}
          {validation && <p className="form-error" role="alert">{validation}</p>}
          {error && <div className="notice error-notice" role="alert">{error} 输入已保留，可修改后重新分析。</div>}
          <div className="form-action-row"><span className="draft-status">{draftStatus}</span>{current && <button className="primary-button" type="submit" disabled={project.busy || analyzing}>{analyzing ? '正在梳理知识点…' : unavailable ? '保存项目并检查分析配置' : version ? '保存需求并重新分析' : '分析项目'}<span aria-hidden="true">→</span></button>}</div>
          <p className="field-help">需求保存在本机，并会发送至已配置的模型服务；所选知识点用于课程检索。请勿输入敏感信息。</p>
        </form></section>}
        {stage === 1 && <button className="manual-entry text-button" onClick={onManual}>直接搜索知识点 <span aria-hidden="true">↗</span></button>}
        {analyzing && <div className="analysis-progress" role="status"><div className="breathing-dots" aria-hidden="true"><i/><i/><i/></div><strong>正在梳理项目知识点</strong><p>识别功能、安排先修关系，再给出学习建议。刷新页面可恢复。</p></div>}
        {inputDirty && stage !== 1 && <p className="notice warning-notice">需求已有未保存修改，请先返回项目描述并重新分析。</p>}
        {stage === 2 && version?.analysis && view && <ProjectConfirmation key={`${view.project_id}:${version.version}`} projectId={view.project_id} version={version} current={current} busy={project.busy} inputDirty={inputDirty} capabilities={capabilities} onSelectedChange={setSelectedCount} onSave={project.save} onConfirm={async (...args) => { const result = await project.confirmAndSearch(...args); if (result) setScreen(null); return result; }}/>} 
        {stage === 3 && version?.confirmation && <ProjectResults version={version} points={view?.points || []} capabilities={capabilities} topic={topic} onCancel={() => void project.cancel()} onRetry={() => void project.retrySearch()} busy={project.busy || !current} current={current}/>}
      </div>
    </main>
    <footer className="site-footer"><span>让学习，发生在项目里。</span><span>需求在本机服务保存 · 分析使用已配置的模型</span></footer>
  </>;
}
