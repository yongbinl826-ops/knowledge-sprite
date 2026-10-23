import type { DeviceState } from './deviceTypes';

export interface KeyValueStorage { get(key: string): Promise<string | null>; set(key: string, value: string): Promise<void> }
const prefix = 'knowledge-sprite.device.v1';
const maxBytes = 4 * 1024 * 1024;
export const emptyDeviceState = (): DeviceState => ({ schema: 1, revision: 0, projects: {}, selected: { id: '' }, inputDraft: null });
const digest = async (value: string) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(n => n.toString(16).padStart(2, '0')).join('');
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string');
const input = (value: unknown): boolean => object(value) && typeof value.name === 'string' && typeof value.requirements === 'string' &&
  ['beginner', 'intermediate', 'advanced', 'any'].includes(String(value.student_level)) && ['zh', 'en', 'any'].includes(String(value.language)) &&
  typeof value.project_context === 'string' && typeof value.technical_version === 'string' && strings(value.preferred_platforms);
const analysis = (value: unknown): boolean => object(value) && typeof value.scope === 'string' && typeof value.technical_plan === 'string' && strings(value.assumptions) &&
  (value.analysis_format === undefined || value.analysis_format === 'concept_list_v1') &&
  (value.functions === undefined || Array.isArray(value.functions) && value.functions.every(item => object(item) && typeof item.id === 'string' && typeof item.name === 'string')) &&
  Array.isArray(value.knowledge_points) && value.knowledge_points.every(point => object(point) && typeof point.id === 'string' && typeof point.name === 'string' &&
    typeof point.description === 'string' && (point.technology === undefined || typeof point.technology === 'string') &&
    (point.why_needed === undefined || typeof point.why_needed === 'string') && (point.learning_goal === undefined || typeof point.learning_goal === 'string') &&
    (point.function_ids === undefined || strings(point.function_ids)) && (point.prerequisite_ids === undefined || strings(point.prerequisite_ids)) &&
    (point.learning_order === undefined || Number.isInteger(point.learning_order) && Number(point.learning_order) >= 1 && Number(point.learning_order) <= 24) &&
    ['learn', 'mastered', 'skip'].includes(String(point.selection)));
const group = (value: unknown): boolean => object(value) && typeof value.knowledge_point_id === 'string' &&
  ['items', 'partial_items', 'review_items'].every(key => value[key] === undefined || Array.isArray(value[key]) && value[key].every(item => object(item) && object(item.resource) && typeof item.resource.resource_id === 'string' && typeof item.resource.url === 'string' && typeof item.resource.title === 'string' && object(item.match) && Array.isArray(item.evidence))) &&
  ['platform_items', 'partial_platform_items', 'review_platform_items'].every(key => value[key] === undefined || object(value[key]) && Object.values(value[key]).every(Array.isArray));
function validState(value: unknown): value is DeviceState {
  const state = value as DeviceState;
  return !!state && state.schema === 1 && Number.isSafeInteger(state.revision) && state.revision >= 0 &&
    !!state.projects && typeof state.projects === 'object' && !Array.isArray(state.projects) &&
    !!state.selected && typeof state.selected.id === 'string' && Object.entries(state.projects).every(([id, project]) =>
      project?.schema === 1 && project.summary?.project_id === id && input(project.input) && Array.isArray(project.views) &&
      project.views.every(view => view.project_id === id && !!view.version && Number.isInteger(view.version.version) && typeof view.version.status === 'string' &&
        input(view.input) && input(view.version.input) && (view.version.analysis === null || analysis(view.version.analysis)) && Array.isArray(view.version.batches) &&
        (view.points === undefined || Array.isArray(view.points) && view.points.every(point => typeof point.project_knowledge_point_id === 'string' && (point.result === null || group(point.result))))) &&
      object(project.drafts) && Object.values(project.drafts).every(analysis) && object(project.learned) && Object.values(project.learned).every(row => object(row) && typeof row.learned === 'boolean' && typeof row.at === 'string')) &&
    (state.inputDraft === null || input(state.inputDraft));
}
export class DeviceStorageError extends Error { constructor(message: string) { super(message); this.name = 'DeviceStorageError'; } }

/** Copy-on-write: old active slot is untouched until verified shadow + head commit.
 * All reads/updates in one WebView are serial. No memory-only success is possible.
 */
export class DeviceStore {
  private queue: Promise<unknown> = Promise.resolve();
  recoveryNotice = '';
  constructor(private readonly storage: KeyValueStorage) {}
  private async slot(index: number) {
    const raw = await this.storage.get(`${prefix}.slot${index}`);
    if (!raw) return null;
    try {
      const envelope = JSON.parse(raw);
      if (envelope.schema !== 1 || typeof envelope.payload !== 'string' || envelope.sha256 !== await digest(envelope.payload)) return null;
      const state: unknown = JSON.parse(envelope.payload);
      return validState(state) ? state : null;
    } catch { return null; }
  }
  private async read(): Promise<{ state: DeviceState; active: number }> {
    const head = await this.storage.get(`${prefix}.head`);
    if (head !== null && head !== '0' && head !== '1') throw new DeviceStorageError('设备存储索引无法读取；旧记录已保留，请勿清除应用数据。');
    if (head !== null) {
      const current = await this.slot(Number(head));
      if (current) return { state: current, active: Number(head) };
      const backup = await this.slot(1 - Number(head));
      if (!backup) throw new DeviceStorageError('设备记录暂时无法读取；原始副本未删除，请勿清除应用数据。');
      this.recoveryNotice = '已读取上一次完整副本；最近一次未完成的保存可能需要重新检查。';
      return { state: backup, active: 1 - Number(head) };
    }
    // Our own earlier schema namespace is copied, never removed or overwritten.
    const legacy = await this.storage.get('knowledge-sprite.device.v0');
    if (legacy) {
      try {
        const value = JSON.parse(legacy);
        if (value.schema !== 0 || !value.projects || !value.selected) throw new Error();
        const migrated = { ...value, schema: 1, revision: 0, inputDraft: value.inputDraft || null,
          projects: Object.fromEntries(Object.entries(value.projects).map(([id, project]) => [id, { ...(project as object), schema: 1, drafts: {}, learned: {} }])) };
        if (!validState(migrated)) throw new Error();
        this.recoveryNotice = '旧版设备记录已读取为内部副本；原始记录保留。';
        return { state: migrated, active: 1 };
      } catch { throw new DeviceStorageError('旧版设备记录格式无法迁移；原始记录已保留。'); }
    }
    return { state: emptyDeviceState(), active: 1 };
  }
  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.queue.then(operation, operation);
    this.queue = next.catch(() => {});
    return next;
  }
  load() { return this.serial(async () => structuredClone((await this.read()).state)); }
  update(change: (state: DeviceState) => void): Promise<DeviceState> {
    return this.serial(async () => {
      let applyingMutation = false;
      try {
        const { state, active } = await this.read();
        const next = structuredClone(state);
        applyingMutation = true; change(next); applyingMutation = false;
        next.revision = state.revision + 1;
        if (!validState(next)) throw new DeviceStorageError('设备数据校验失败，未覆盖旧记录。');
        const payload = JSON.stringify(next);
        if (new TextEncoder().encode(payload).byteLength > maxBytes) throw new DeviceStorageError('设备记录已达本机保存上限，旧记录未被覆盖；请减少本次内容后再试。');
        const shadow = 1 - active, key = `${prefix}.slot${shadow}`;
        const envelope = JSON.stringify({ schema: 1, payload, sha256: await digest(payload) });
        await this.storage.set(key, envelope);
        if (await this.storage.get(key) !== envelope) throw new Error('shadow verification');
        await this.storage.set(`${prefix}.head`, String(shadow));
        if (await this.storage.get(`${prefix}.head`) !== String(shadow)) throw new Error('commit verification');
        return structuredClone(next);
      } catch (error) {
        if (applyingMutation) throw error; // Business guards are not disk failures.
        if (error instanceof DeviceStorageError) throw error;
        throw new DeviceStorageError('未能可靠保存到本机；旧记录仍保留。请释放设备空间后重新保存，不会自动提交服务器。');
      }
    });
  }
}
