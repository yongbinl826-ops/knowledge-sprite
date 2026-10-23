import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { openSnapshotStream } from './snapshotStream';
import type { ProjectAnalysis, ProjectInput, ProjectSummary, ProjectView } from './projectTypes';
import { reviewedTopicTechnologies } from './reviewedTopicTechnologies';

const pointerKey = 'knowledge-guide-project-v1';
const activeStatuses = new Set(['analyzing', 'running']);
const isActive = (value: ProjectView) => value.pipeline ? !value.pipeline.terminal : activeStatuses.has(value.version?.status || '')
  || !!value.version?.batches.some(batch => batch.status === 'submitted' || ['queued', 'running'].includes(batch.job_status || ''));
function savedProject() {
  const query = new URLSearchParams(location.search);
  if (query.get('project')) return { id: query.get('project')!, version: Number(query.get('version')) || undefined };
  try { return { id: localStorage.getItem(pointerKey) || '', version: undefined }; } catch { return { id: '', version: undefined }; }
}
function rememberProject(id: string, version?: number) {
  try { if (id) localStorage.setItem(pointerKey, id); else localStorage.removeItem(pointerKey); } catch { /* URL still supports recovery. */ }
  const url = new URL(location.href);
  if (id) url.searchParams.set('project', id); else url.searchParams.delete('project');
  if (version) url.searchParams.set('version', String(version)); else url.searchParams.delete('version');
  history.replaceState(null, '', url);
}

export function useProject() {
  const [pointer, setPointer] = useState(savedProject);
  const [view, setView] = useState<ProjectView | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(!!pointer.id);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const lock = useRef(false);
  const mounted = useRef(true);
  const actionController = useRef<AbortController | null>(null);
  const watchController = useRef<AbortController | null>(null);
  const watchGeneration = useRef(0);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; actionController.current?.abort(); }; }, []);
  const refreshList = useCallback(async (signal?: AbortSignal) => {
    try { const next = await api<{ projects: ProjectSummary[] }>('/api/projects', { signal }); if (mounted.current && !signal?.aborted) setProjects(next.projects); }
    catch (err) { if (mounted.current && !signal?.aborted) setError(`项目列表暂时无法读取：${(err as Error).message}`); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void refreshList(controller.signal); return () => controller.abort(); }, [refreshList]);

  useEffect(() => {
    if (busy) return;
    if (!pointer.id) { setLoading(false); return; }
    const controller = new AbortController();
    watchController.current = controller;
    const generation = ++watchGeneration.current;
    const current = () => mounted.current && !controller.signal.aborted && generation === watchGeneration.current;
    let timer = 0;
    let failures = 0;
    let watchedVersion = pointer.version;
    let allowStream = true;
    let closeStream = () => {};
    const apply = (next: ProjectView) => {
      if (!current()) return;
      if (next.project_id !== pointer.id || (watchedVersion && next.version?.version !== watchedVersion)) throw new Error('项目或版本编号不一致，未替换当前结果。');
      setView(next); setLoading(false); setPollError(''); failures = 0;
    };
    const poll = async () => {
      try {
        const next = await api<ProjectView>(`/api/projects/${encodeURIComponent(pointer.id)}/results${watchedVersion ? `?version=${watchedVersion}` : ''}`, { signal: controller.signal });
        if (!current()) return;
        apply(next);
        if (!isActive(next)) return;
        if (allowStream && next.pipeline) {
          allowStream = false;
          watchedVersion = next.version?.version;
          closeStream = openSnapshotStream<ProjectView>({
            url: `/api/projects/${encodeURIComponent(pointer.id)}/events${watchedVersion ? `?version=${watchedVersion}` : ''}`,
            signal: controller.signal,
            onSnapshot: snapshot => { apply(snapshot); if (!isActive(snapshot)) closeStream(); },
            onComplete: snapshot => { if (!snapshot || isActive(snapshot)) throw new Error('缺少最终项目状态'); apply(snapshot); },
            onFallback: () => { if (current()) void poll(); },
          });
          return;
        }
      } catch (err) {
        if (!current()) return;
        failures += 1; setLoading(false);
        setPollError(`项目状态暂时无法读取：${(err as Error).message}${failures < 3 ? ' 正在重试。' : ' 可点击重新读取。'}`);
        if (failures >= 3) return;
      }
      if (current()) timer = window.setTimeout(poll, 1500);
    };
    void poll();
    return () => { controller.abort(); closeStream(); window.clearTimeout(timer); };
  }, [pointer.id, pointer.version, revision, busy]);

  const selectProject = (id: string, version?: number) => {
    if (lock.current) return;
    watchGeneration.current += 1; watchController.current?.abort();
    setView(null); setError(''); setPollError(''); setNotice(''); setLoading(!!id); setPointer({ id, version }); rememberProject(id, version); setRevision(value => value + 1);
  };
  const perform = async (operation: (signal: AbortSignal) => Promise<ProjectView>, success: string) => {
    if (lock.current) return;
    watchGeneration.current += 1; watchController.current?.abort();
    lock.current = true; setBusy(true); setError(''); setPollError(''); setNotice('');
    const controller = new AbortController(); actionController.current = controller;
    try {
      const next = await operation(controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      setView(next); setPointer({ id: next.project_id, version: next.version?.version });
      rememberProject(next.project_id, next.version?.version); setNotice(success); setRevision(value => value + 1);
      void refreshList();
      return next;
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) { setError((err as Error).message); setRevision(value => value + 1); }
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  };
  const post = (id: string, action: string, body: unknown, signal: AbortSignal) => api<ProjectView>(`/api/projects/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: JSON.stringify(body), signal });
  const keepMutation = (next: ProjectView, signal: AbortSignal) => {
    if (mounted.current && !signal.aborted) {
      setView(next); setPointer({ id: next.project_id, version: next.version?.version });
      rememberProject(next.project_id, next.version?.version);
    }
    return next;
  };
  const analyze = (input: ProjectInput) => perform(async signal => {
    let current = view;
    if (!current) {
      current = await api<ProjectView>('/api/projects', { method: 'POST', body: JSON.stringify(input), signal });
      // Keep the saved input recoverable even when the subsequent analysis request fails.
      if (mounted.current && !signal.aborted) { setView(current); setPointer({ id: current.project_id, version: undefined }); rememberProject(current.project_id); }
    }
    return post(current.project_id, 'analyze', { expected_version: current.current_version, input }, signal);
  }, '项目需求已保存，分析通过后请逐项确认。');
  const save = (analysis: ProjectAnalysis) => perform(signal => {
    if (!view?.version) throw new Error('请先完成项目分析。');
    return post(view.project_id, 'edit', { expected_version: view.version.version, analysis }, signal);
  }, '修改已保存为新版本，需要重新确认。');
  const confirmAndSearch = (analysis: ProjectAnalysis, dirty: boolean) => perform(async signal => {
    if (!view?.version) throw new Error('请先完成项目分析。');
    let current = view;
    if (dirty) current = keepMutation(await post(current.project_id, 'edit', { expected_version: current.version!.version, analysis }, signal), signal);
    current = keepMutation(await post(current.project_id, 'confirm', { version: current.version!.version, reviewed_topic_technologies: reviewedTopicTechnologies(analysis) }, signal), signal);
    if (analysis.knowledge_points.some(point => point.selection === 'learn')) current = await post(current.project_id, 'search', { version: current.version!.version }, signal);
    return current;
  }, analysis.knowledge_points.some(point => point.selection === 'learn') ? '已确认，按勾选的知识点分批查找推荐视频。' : '已保存选择；没有勾选知识点，未创建检索任务。');
  const cancel = () => perform(signal => {
    if (!view?.version) throw new Error('没有可取消的项目检索。');
    return post(view.project_id, 'cancel', { version: view.version.version }, signal);
  }, '取消已提交，尚未启动的批次将停止，已取得的结果继续保留。');

  const retrySearch = () => perform(async signal => {
    if (!view?.version?.analysis) throw new Error('请先完成项目分析。');
    if (view.version.version !== view.current_version) throw new Error('历史版本仅供查看，请返回最新版本重新检索。');
    // A retry gets a fresh version and budget; the previous evidence stays intact.
    let next = keepMutation(await post(view.project_id, 'edit', { expected_version: view.version.version, analysis: view.version.analysis }, signal), signal);
    next = keepMutation(await post(next.project_id, 'confirm', { version: next.version!.version, reviewed_topic_technologies: reviewedTopicTechnologies(next.version!.analysis!) }, signal), signal);
    return post(next.project_id, 'search', { version: next.version!.version }, signal);
  }, '已创建新的检索版本；上次结果继续保留。');

  return { view, projects, busy, loading, error: error || pollError, notice, analyze, save, confirmAndSearch, cancel, retrySearch, selectProject,
    refresh: () => { setError(''); setPollError(''); setRevision(value => value + 1); }, newProject: () => selectProject('') };
}
