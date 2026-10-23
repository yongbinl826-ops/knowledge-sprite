import { useCallback, useEffect, useRef, useState } from 'react';
import type { ProjectAnalysis, ProjectInput, ProjectView } from '../projectTypes';
import type { LocalProjectService } from './localProjectService';

export function useDeviceProject(service: LocalProjectService, configurationError = '') {
  const [snapshot, setSnapshot] = useState<Awaited<ReturnType<LocalProjectService['snapshot']>> | null>(null);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [watchRevision, setWatchRevision] = useState(0);
  const mounted = useRef(true), lock = useRef(false), action = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    try { const next = await service.snapshot(); if (mounted.current) { setSnapshot(next); setLoading(false); } return next; }
    catch (reason) { if (mounted.current) { setLoading(false); setError((reason as Error).message); } throw reason; }
  }, [service]);
  useEffect(() => {
    mounted.current = true; void load().catch(() => {});
    const unsubscribe = service.subscribe(() => { void load().catch(() => {}); });
    return () => { mounted.current = false; action.current?.abort(); unsubscribe(); };
  }, [service, load]);
  const ticket = snapshot?.project?.ticket;
  const ticketKey = `${snapshot?.state.selected.id || ''}:${ticket?.id || ''}`;
  useEffect(() => {
    if (busy || !ticket?.id || configurationError || !['prepared', 'submitted', 'uncertain'].includes(ticket.phase)) return;
    // Authorization-bearing fetch only; never EventSource or a token in a URL.
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined, failures = 0;
    const poll = async () => {
      if (controller.signal.aborted) return;
      if (!navigator.onLine) { setNotice('当前离线，可继续查看本机记录。联网后只读取原任务，不会重新提交。'); return; }
      try {
        await service.poll(controller.signal); if (controller.signal.aborted) return;
        setError(''); failures = 0;
      } catch (reason) {
        if (controller.signal.aborted) return;
        failures += 1; setError(`任务状态暂未确认：${(reason as Error).message}。${failures < 3 ? '稍后只重新读取状态。' : '已暂停读取；可点击重新读取。'}`);
        if (failures >= 3) return;
      }
      const next = await service.snapshot();
      if (next.project?.ticket?.id !== ticket.id || !['prepared', 'submitted', 'uncertain'].includes(next.project.ticket.phase)) return;
      const wait = Math.max(1500 * 2 ** failures, Date.parse(next.project.ticket.nextPollAt || '') - Date.now() || 0);
      timer = setTimeout(() => { void poll().catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message); }); }, Math.min(wait, 2 * 60 * 60 * 1000));
    };
    // Allow a pending POST to settle first. Even cold-start recovery is GET-only.
    timer = setTimeout(() => { void poll().catch(reason => setError((reason as Error).message)); }, 1500);
    const resume = () => { if (timer) clearTimeout(timer); timer = setTimeout(() => { void poll().catch(reason => setError((reason as Error).message)); }, 1500); };
    window.addEventListener('online', resume); window.addEventListener('device-resume', resume);
    return () => { controller.abort(); clearTimeout(timer); window.removeEventListener('online', resume); window.removeEventListener('device-resume', resume); };
    // Ticket changes stop/rebind a watcher; persistence revisions never create tight polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketKey, service, watchRevision, configurationError, busy]);
  const perform = async (operation: (signal: AbortSignal) => Promise<ProjectView>, message: string, network = false) => {
    if (lock.current) return;
    if (network && configurationError) { setError(configurationError); return; }
    lock.current = true; setBusy(true); setError(''); setNotice('');
    const controller = new AbortController(); action.current = controller;
    try { const result = await operation(controller.signal); await load(); if (mounted.current) setNotice(message); return result; }
    catch (reason) { if (mounted.current) { setError((reason as Error).message); await load().catch(() => {}); } }
    finally { lock.current = false; if (mounted.current) { setBusy(false); setWatchRevision(value => value + 1); } }
  };
  const selectProject = (id: string, version?: number) => {
    if (lock.current) return;
    setError(''); setNotice('');
    void service.select(id, version).catch(reason => setError((reason as Error).message));
  };
  const localWrite = async (operation: () => Promise<unknown>) => {
    try { await operation(); setError(''); }
    catch (reason) { setError((reason as Error).message); throw reason; }
  };
  const view = snapshot?.view || null;
  return {
    view, projects: snapshot?.projects || [], busy, loading, error, notice: notice || service.store.recoveryNotice,
    analyze: (input: ProjectInput) => perform(signal => service.analyze(input, signal), '输入已在本机保存；临时分析任务仅在明确操作后提交。', true),
    save: (analysis: ProjectAnalysis) => perform(() => service.save(analysis), '已保存到本机新版本，可离线查看。'),
    confirmAndSearch: (analysis: ProjectAnalysis, dirty: boolean) => !navigator.onLine || !!configurationError
      ? perform(() => service.confirmLocal(analysis, dirty), '选择已在本机确认；未开始课程检索。联网并配置服务后，需再次明确点击查找视频。')
      : perform(signal => service.confirmAndSearch(analysis, dirty, signal), '选择已保存在设备；正在读取本次视频任务。', analysis.knowledge_points.some(p => p.selection === 'learn')),
    retrySearch: () => perform(signal => service.retrySearch(signal), '已明确创建新版本与新临时任务；旧结果保留。', true),
    cancel: () => perform(signal => service.cancel(signal), '取消状态已保存到本机。', true),
    selectProject, newProject: () => selectProject(''),
    refresh: () => { setError(''); void load().catch(() => {}); setWatchRevision(value => value + 1); },
    inputDraft: snapshot?.state.inputDraft || null,
    saveInputDraft: (input: ProjectInput) => localWrite(() => service.inputDraft(input)),
    editDraft: view?.version ? snapshot?.project?.drafts[view.version.version] : undefined,
    saveEditDraft: (analysis: ProjectAnalysis) => view?.version ? localWrite(() => service.draft(view.project_id, view.version!.version, analysis)) : Promise.resolve(),
    progress: snapshot?.project?.learned || {},
    toggleLearned: (pointId: string, learned: boolean) => view?.version ? localWrite(() => service.learned(view.project_id, view.version!.version, pointId, learned)) : Promise.resolve(),
    directSearch: (request: import('../types').SearchRequest) => perform(signal => service.directSearch(request, signal), '直接检索已保存到本机项目。', true),
    canRemove: !ticket || !['prepared', 'submitted', 'uncertain'].includes(ticket.phase),
    removeProject: async () => { if (lock.current || !view) return; lock.current = true; setBusy(true);
      try { await service.remove(view.project_id); await load(); setNotice('已从这台设备删除项目。'); }
      catch (reason) { setError((reason as Error).message); }
      finally { lock.current = false; setBusy(false); }
    },
  };
}
