import type { ProjectAnalysis, ProjectInput, ProjectSummary, ProjectView } from '../projectTypes';
import type { SearchRequest, SearchResults } from '../types';
import type { DeviceState, LocalProject, MobileTask, MobileTaskBody, TaskTicket } from './deviceTypes';
import { DeviceStore } from './deviceStorage.ts';
import { createTicket, MobileApi, MobileHttpError } from './mobileApi.ts';
import { reviewedTopicTechnologies } from '../reviewedTopicTechnologies.ts';
import { DraftWriter } from './draftWriter.ts';

const stamp = () => new Date().toISOString();
const activeTicket = (ticket?: TaskTicket) => !!ticket && ['prepared', 'submitted', 'uncertain'].includes(ticket.phase);
// Retain the same read capability while a completed recommendation receives
// optional catalog updates; recovery must never submit another search.
const finalTask = (task: MobileTask) => !['queued', 'running'].includes(task.status) && task.result?.pipeline?.catalog_pending !== true;
const requestInput = (input: ProjectInput) => structuredClone(input);
function localView(project: LocalProject, version?: number): ProjectView {
  const number = version || project.summary.current_version;
  const view = structuredClone(project.views.find(item => item.version?.version === number)!);
  if (!view) throw new Error('本机未保存此版本。');
  return { ...view, current_version: project.summary.current_version, versions: project.views.map(item => ({
    version: item.version!.version, status: item.version!.status, created_at: item.version!.created_at,
  })) };
}
function addVersion(project: LocalProject, input: ProjectInput, analysis: ProjectAnalysis | null, status: string) {
  const number = project.summary.current_version + 1;
  const view: ProjectView = { project_id: project.summary.project_id, current_version: number, input: requestInput(input), versions: [],
    version: { version: number, status, input: requestInput(input), analysis: structuredClone(analysis), confirmation: null,
      batches: [], error: null, created_at: stamp() }, points: [], functions: analysis?.functions || [] };
  project.views.push(view); project.summary.current_version = number; project.summary.name = input.name;
  project.summary.updated_at = stamp(); project.input = requestInput(input);
  return view;
}
function searchBody(project: LocalProject, analysis: ProjectAnalysis): MobileTaskBody {
  if (project.mode === 'direct') return { kind: 'direct_search', request: {
    knowledge_points: analysis.knowledge_points.filter(point => point.selection === 'learn').map(point => point.name),
    student_level: project.input.student_level, language: project.input.language, project_context: project.input.project_context,
    technical_version: project.input.technical_version, preferred_platforms: project.input.preferred_platforms,
  } };
  return { kind: 'search', input: requestInput(project.input), analysis: structuredClone(analysis), reviewed_topic_technologies: reviewedTopicTechnologies(analysis) };
}
export class LocalProjectService {
  private listeners = new Set<() => void>();
  private drafts = new DraftWriter<DeviceState>(change => this.commit(change));
  constructor(readonly store: DeviceStore, readonly api: MobileApi) {}
  subscribe(listener: () => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  private async commit(change: (state: DeviceState) => void) {
    const result = await this.store.update(change); this.listeners.forEach(listener => listener()); return result;
  }
  async snapshot() {
    const state = await this.store.load(); const project = state.projects[state.selected.id];
    return { state, view: project ? localView(project, state.selected.version) : null,
      project, projects: Object.values(state.projects).map(p => p.summary).sort((a, b) => b.updated_at.localeCompare(a.updated_at)) };
  }
  flushDrafts() { return this.drafts.flush(); }
  async select(id: string, version?: number) { await this.flushDrafts(); return this.commit(state => {
    if (id && !state.projects[id]) throw new Error('本机没有此项目。');
    if (id && version && !state.projects[id].views.some(v => v.version?.version === version)) throw new Error('本机没有此版本。');
    state.selected = { id, version };
  }); }
  inputDraft(input: ProjectInput) { const saved = requestInput(input); return this.drafts.save('input', state => { state.inputDraft = saved; }); }
  draft(id: string, version: number, analysis: ProjectAnalysis) { const saved = structuredClone(analysis); return this.drafts.save(`edit:${id}:${version}`, state => {
    const project = state.projects[id]; if (!project || project.summary.current_version !== version) throw new Error('此历史版本仅供查看。');
    project.drafts[version] = saved;
  }); }
  learned(id: string, version: number, point: string, learned: boolean) { return this.commit(state => {
    const project = state.projects[id];
    if (!project?.views.find(view => view.version?.version === version)?.version?.analysis?.knowledge_points.some(p => p.id === point)) throw new Error('未找到此本机知识点。');
    project.learned[`${version}:${point}`] = { learned, at: stamp() };
  }); }
  async remove(id: string) { await this.flushDrafts(); return this.commit(state => {
    const project = state.projects[id]; if (!project) return;
    if (activeTicket(project.ticket)) throw new Error('请先明确取消或读取临时任务的最终状态，再删除本机项目。');
    delete state.projects[id];
    if (state.selected.id === id) { state.selected = { id: '' }; state.inputDraft = null; }
  }); }
  private current(state: DeviceState): LocalProject {
    const project = state.projects[state.selected.id];
    if (!project || (state.selected.version && state.selected.version !== project.summary.current_version)) throw new Error('请先返回本机最新版本。');
    return project;
  }
  private noActive(project: LocalProject) {
    if (activeTicket(project.ticket) && Date.parse(project.ticket!.expiresAt) > Date.now()) throw new Error('上次任务结果尚未确认。请先重新读取状态；不会重复提交。');
  }
  private async stopCatalogBeforeMutation(signal?: AbortSignal) {
    await this.flushDrafts();
    const { state, project } = await this.snapshot();
    if (!project) return;
    this.current(state);
    const ticket = project.ticket;
    const pipeline = project.views.find(view => view.version?.version === ticket?.version)?.pipeline;
    if (activeTicket(ticket) && Date.parse(ticket!.expiresAt) > Date.now() && pipeline?.terminal && pipeline.catalog_pending) {
      // A new explicit action may replace completed recommendations. First
      // release their optional work; ordinary polling never enters this path.
      await this.cancel(signal);
    }
  }
  async save(analysis: ProjectAnalysis, signal?: AbortSignal) {
    await this.stopCatalogBeforeMutation(signal);
    await this.commit(state => { const project = this.current(state); this.noActive(project);
      addVersion(project, project.input, analysis, 'analyzed'); state.selected.version = project.summary.current_version;
    });
    return (await this.snapshot()).view!;
  }
  private async prepare(body: MobileTaskBody, analysis: ProjectAnalysis | null, input: ProjectInput, reuseCurrent = false, signal?: AbortSignal) {
    await this.stopCatalogBeforeMutation(signal);
    let ticket!: TaskTicket;
    await this.commit(state => {
      let project = state.projects[state.selected.id];
      if (!project) {
        const id = crypto.randomUUID(); const summary: ProjectSummary = { project_id: id, name: input.name, current_version: 0, created_at: stamp(), updated_at: stamp() };
        project = { schema: 1, mode: body.kind === 'direct_search' ? 'direct' : 'project', summary, input: requestInput(input), views: [], drafts: {}, learned: {} }; state.projects[id] = project; state.selected = { id };
      } else { this.current(state); this.noActive(project); }
      const view = reuseCurrent ? project.views.at(-1)! : addVersion(project, input, analysis, body.kind === 'analysis' ? 'analyzing' : 'confirmed');
      view.version!.status = body.kind === 'analysis' ? 'analyzing' : 'running'; view.version!.error = null;
      if (body.kind !== 'analysis') view.version!.confirmation = { confirmed_at: stamp(), selected_ids: analysis!.knowledge_points.filter(p => p.selection === 'learn').map(p => p.id) };
      ticket = createTicket(project.summary.project_id, view.version!.version, body);
      project.ticket = ticket; state.selected.version = view.version!.version; state.inputDraft = null;
      delete project.drafts[view.version!.version];
    });
    return ticket;
  }
  private async send(ticket: TaskTicket, signal?: AbortSignal) {
    // Persist the send intent first. A crash here only permits GET after restart.
    await this.commit(state => { const saved = state.projects[ticket.projectId]?.ticket;
      if (!saved || saved.id !== ticket.id || saved.phase !== 'prepared' || saved.body !== ticket.body) throw new Error('任务已提交或本机记录不一致，未重复发送。');
      saved.phase = 'submitted';
    });
    try { await this.apply(ticket, await this.api.task(ticket, 'POST', signal)); }
    catch (error) { await this.noteFailure(ticket, error); throw new Error('提交结果尚未确认，输入和任务凭据已保存在本机。请重新读取状态，不会自动再次提交。'); }
    return (await this.snapshot()).view!;
  }
  async analyze(input: ProjectInput, signal?: AbortSignal) { return this.send(await this.prepare({ kind: 'analysis', input: requestInput(input) }, null, input, false, signal), signal); }
  async confirmLocal(analysis: ProjectAnalysis, dirty: boolean, signal?: AbortSignal) {
    await this.stopCatalogBeforeMutation(signal);
    if (dirty) await this.save(analysis, signal);
    await this.commit(state => {
      const project = this.current(state); this.noActive(project);
      const latest = project.views.at(-1)!;
      if (latest.version!.confirmation?.local_only === true && JSON.stringify(latest.version!.analysis) === JSON.stringify(analysis)) {
        state.selected.version = latest.version!.version; return;
      }
      const view = project.views.at(-1)!.version!.confirmation ? addVersion(project, project.input, analysis, 'confirmed') : project.views.at(-1)!;
      view.version!.confirmation = { confirmed_at: stamp(), local_only: true, selected_ids: analysis.knowledge_points.filter(point => point.selection === 'learn').map(point => point.id), reviewed_topic_technologies: reviewedTopicTechnologies(analysis) };
      view.version!.status = 'confirmed'; view.version!.error = null; state.selected.version = view.version!.version;
      delete view.pipeline; view.points = []; view.version!.batches = [];
      delete project.drafts[view.version!.version];
    });
    return (await this.snapshot()).view!;
  }
  async confirmAndSearch(analysis: ProjectAnalysis, dirty: boolean, signal?: AbortSignal) {
    const snapshot = await this.snapshot(); if (!snapshot.project || !snapshot.view?.version) throw new Error('请先分析本机项目。');
    if (dirty) await this.save(analysis, signal);
    if (!analysis.knowledge_points.some(point => point.selection === 'learn')) {
      return this.confirmLocal(analysis, false, signal);
    }
    const latest = await this.snapshot();
    const reuseAnalyzedVersion = !latest.view?.version?.confirmation;
    const ticket = await this.prepare(searchBody(snapshot.project, analysis), analysis, snapshot.project.input, reuseAnalyzedVersion, signal);
    return this.send(ticket, signal);
  }
  async retrySearch(signal?: AbortSignal) {
    const { view, project } = await this.snapshot(); if (!view?.version?.analysis || !project) throw new Error('本机尚无分析结果。');
    const analysis = view.version.analysis;
    return this.send(await this.prepare(searchBody(project, analysis), analysis, project.input, false, signal), signal);
  }
  async directSearch(request: SearchRequest, signal?: AbortSignal) {
    const input: ProjectInput = { ...request, name: request.knowledge_points.join('、').slice(0, 160), requirements: '直接检索专业知识点' };
    const analysis: ProjectAnalysis = { analysis_format: 'concept_list_v1', scope: input.requirements, technical_plan: '', assumptions: [], knowledge_points: request.knowledge_points.map((name, index) => ({ id: `direct-${index + 1}`, name, description: '', technology: '', selection: 'learn' })) };
    await this.select('');
    return this.send(await this.prepare({ kind: 'direct_search', request: structuredClone(request) }, analysis, input, false, signal), signal);
  }
  private async apply(ticket: TaskTicket, task: MobileTask) {
    const kind = (JSON.parse(ticket.body) as MobileTaskBody).kind;
    if (task.task_id !== ticket.id || task.kind !== kind || !Number.isFinite(Date.parse(task.expires_at)) || !['queued', 'running', 'completed', 'partial', 'failed', 'cancelled'].includes(task.status)) throw new Error('服务任务身份或状态不一致，保留本机记录。');
    const revision = task.snapshot_revision || task.result?.snapshot_revision;
    const fingerprint = JSON.stringify(revision ? { revision, status: task.status, error: task.error, expires_at: task.expires_at } : task);
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(fingerprint)))].map(n => n.toString(16).padStart(2, '0')).join('');
    const savedBefore = (await this.store.load()).projects[ticket.projectId]?.ticket;
    if (savedBefore?.id === ticket.id && savedBefore.snapshotRevision === hash && !savedBefore.message) return false;
    await this.commit(state => {
      const project = state.projects[ticket.projectId]; const saved = project?.ticket;
      if (!saved || saved.id !== ticket.id) return; // Older responses never overwrite a newer action.
      const view = project.views.find(v => v.version?.version === ticket.version)!;
      saved.expiresAt = new Date(Math.min(Date.parse(saved.expiresAt), Date.parse(task.expires_at))).toISOString(); saved.nextPollAt = undefined; saved.message = undefined;
      saved.snapshotRevision = hash;
      if (task.result) {
        if ('version' in task.result) {
          const remote = task.result; if (!remote.version) throw new Error('服务未返回项目版本。');
          // The local UUID/version remain authoritative; server IDs are processing-only.
          const mapped = structuredClone(remote);
          Object.assign(view, mapped, { project_id: ticket.projectId, current_version: project.summary.current_version,
            input: requestInput(view.input), versions: [] });
          view.version = { ...mapped.version!, version: ticket.version, input: requestInput(view.input) };
        } else {
          const result = task.result as SearchResults;
          const points = view.version!.analysis!.knowledge_points;
          let selectedIndex = 0;
          view.points = points.map(point => {
            const selected = point.selection === 'learn', group = selected ? result.groups[selectedIndex++] : undefined;
            return { project_knowledge_point_id: point.id, name: point.name, selection: point.selection,
              status: selected ? result.status : 'not_selected', batch_id: null, job_id: selected ? result.job_id : null,
              knowledge_point_id: group?.knowledge_point_id || null, result: group || null };
          });
          view.pipeline = result.pipeline; view.version!.status = result.status;
        }
      }
      if (!task.result && finalTask(task)) {
        view.version!.status = kind === 'analysis' ? 'analysis_failed' : task.status === 'cancelled' ? 'cancelled' : 'failed';
        view.version!.error = task.error?.message || '任务未返回可保存的结果；本机原始输入仍保留。';
      }
      if (finalTask(task)) { saved.phase = 'complete'; saved.capability = ''; }
      project.summary.updated_at = stamp();
    });
    return true;
  }
  private async noteFailure(ticket: TaskTicket, error: unknown) {
    await this.commit(state => { const saved = state.projects[ticket.projectId]?.ticket; if (!saved || saved.id !== ticket.id || !activeTicket(saved)) return;
      const message = error instanceof Error ? error.message : '网络暂不可用'; saved.message = message;
      if (error instanceof MobileHttpError && error.status === 404 || Date.parse(saved.expiresAt) <= Date.now()) {
        saved.phase = 'expired'; saved.capability = '';
        const view = state.projects[ticket.projectId].views.find(v => v.version?.version === ticket.version)!;
        view.version!.status = JSON.parse(saved.body).kind === 'analysis' ? 'analysis_failed' : 'interrupted';
        view.version!.error = '临时任务已过期或服务已重启。本机输入和已保存结果保留，请明确操作后重新分析或检索。';
        if (view.pipeline) view.pipeline.terminal = true;
      } else { saved.phase = 'uncertain'; if (error instanceof MobileHttpError && error.status === 429) saved.nextPollAt = new Date(Date.now() + error.retryAfterMs).toISOString(); }
    });
  }
  async poll(signal?: AbortSignal) {
    const { project } = await this.snapshot(); const ticket = project?.ticket;
    if (!activeTicket(ticket)) return;
    if (Date.parse(ticket!.expiresAt) <= Date.now()) { await this.noteFailure(ticket!, new MobileHttpError('临时任务已过期', 404)); return; }
    if (ticket!.nextPollAt && Date.parse(ticket!.nextPollAt) > Date.now()) return;
    try { return await this.apply(ticket!, await this.api.task(ticket!, 'GET', signal)); }
    catch (error) { if (signal?.aborted) return; await this.noteFailure(ticket!, error); throw error; }
  }
  async cancel(signal?: AbortSignal) {
    const { project } = await this.snapshot(); const ticket = project?.ticket;
    if (!activeTicket(ticket)) throw new Error('当前没有待取消的临时任务。');
    try { await this.apply(ticket!, await this.api.cancel(ticket!, signal)); }
    catch (error) { await this.noteFailure(ticket!, error); throw new Error('取消状态尚未确认，请重新读取，不会自动再次取消。'); }
    return (await this.snapshot()).view!;
  }
}
