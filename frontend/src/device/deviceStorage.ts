import type { DeviceState } from './deviceTypes';
import { MAX_PROJECT_KNOWLEDGE_POINTS } from '../projectLimits.ts';

export interface KeyValueStorage { get(key: string): Promise<string | null>; set(key: string, value: string): Promise<void>; remove?(key: string): Promise<void> }
const prefix = 'knowledge-sprite.device.v2';
const legacyPrefix = 'knowledge-sprite.device.v1';
const maxBytes = 4 * 1024 * 1024;
export const emptyDeviceState = (): DeviceState => ({ schema: 1, revision: 0, projects: {}, selected: { id: '' }, inputDraft: null });
const digest = async (value: string) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(n => n.toString(16).padStart(2, '0')).join('');
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string');
const blockHash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
type DeviceManifest = { schema: 2; revision: number; selected: DeviceState['selected']; inputDraft: string | null;
  projects: Record<string, { metadata: string; views: string[] }> };
function validManifest(value: unknown): value is DeviceManifest {
  return object(value) && value.schema === 2 && Number.isSafeInteger(value.revision) && Number(value.revision) >= 0 &&
    object(value.selected) && typeof value.selected.id === 'string' &&
    (value.selected.version === undefined || Number.isSafeInteger(value.selected.version) && Number(value.selected.version) > 0) &&
    (value.inputDraft === null || blockHash(value.inputDraft)) && object(value.projects) &&
    Object.values(value.projects).every(entry => object(entry) && blockHash(entry.metadata) && Array.isArray(entry.views) && entry.views.every(blockHash));
}
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
    (point.learning_order === undefined || Number.isInteger(point.learning_order) && Number(point.learning_order) >= 1 && Number(point.learning_order) <= MAX_PROJECT_KNOWLEDGE_POINTS) &&
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
  private blocks = new Map<string, string>();
  private hashes = new Map<string, string>();
  // Content is immutable: retain its verified identity even when its raw bytes
  // leave the bounded cache, so large histories do not cross the bridge again.
  private verifiedHashes = new Set<string>();
  private snapshotCache?: { raw: string; state: DeviceState };
  recoveryNotice = '';
  constructor(private readonly storage: KeyValueStorage) {}
  private remember(hash: string, raw: string) {
    if (this.blocks.size >= 256 && !this.blocks.has(hash)) {
      const oldest = this.blocks.keys().next().value!;
      this.hashes.delete(this.blocks.get(oldest)!); this.blocks.delete(oldest);
    }
    this.blocks.set(hash, raw); this.hashes.set(raw, hash);
    this.verifiedHashes.add(hash);
  }
  private async slot(index: number, namespace = prefix) {
    const raw = await this.storage.get(`${namespace}.slot${index}`);
    if (!raw) return null;
    if (namespace === prefix && this.snapshotCache?.raw === raw) return this.snapshotCache.state;
    try {
      const envelope = JSON.parse(raw);
      if (![1, 2].includes(envelope.schema) || typeof envelope.payload !== 'string' || envelope.sha256 !== await digest(envelope.payload)) return null;
      let state: unknown = JSON.parse(envelope.payload);
      if (envelope.schema === 2 && namespace === prefix) {
        if (!validManifest(state)) return null;
        const manifest = state;
        const projects: DeviceState['projects'] = {};
        for (const [id, entry] of Object.entries(manifest.projects)) {
          if (!entry || !Array.isArray(entry.views)) return null;
          const metadata = JSON.parse(await this.block(entry.metadata));
          const views = [];
          for (const hash of entry.views) views.push(JSON.parse(await this.block(hash)));
          projects[id] = { ...metadata, views };
        }
        state = { schema: 1, revision: manifest.revision, selected: manifest.selected, projects,
          inputDraft: manifest.inputDraft ? JSON.parse(await this.block(manifest.inputDraft)) : null };
      }
      if (!validState(state)) return null;
      if (namespace === prefix) this.snapshotCache = { raw, state };
      return state;
    } catch { return null; }
  }
  private async block(hash: string): Promise<string> {
    if (!blockHash(hash)) throw new Error('invalid block identity');
    const cached = this.blocks.get(hash);
    if (cached !== undefined) return cached;
    const raw = await this.storage.get(`${prefix}.block.${hash}`);
    if (raw === null || await digest(raw) !== hash) throw new Error('invalid block');
    this.remember(hash, raw);
    return raw;
  }
  private async writeBlock(value: unknown): Promise<string> {
    const raw = JSON.stringify(value);
    if (new TextEncoder().encode(raw).byteLength > maxBytes) throw new DeviceStorageError('单份设备记录已达保存上限；原始记录保留。');
    let hash = this.hashes.get(raw);
    if (hash) return hash;
    hash = await digest(raw);
    if (this.verifiedHashes.has(hash)) return hash;
    const key = `${prefix}.block.${hash}`;
    // Immutable content blocks are installed before the manifest commit. A
    // failed operation leaves only unreachable bytes, never a partial record.
    if (await this.storage.get(key) !== raw) await this.storage.set(key, raw);
    if (await this.storage.get(key) !== raw) throw new Error('block verification');
    this.remember(hash, raw);
    return hash;
  }
  private async references(index: number): Promise<Set<string> | null> {
    try {
      const raw = await this.storage.get(`${prefix}.slot${index}`);
      if (!raw) return null;
      const envelope = JSON.parse(raw);
      if (envelope.schema !== 2 || typeof envelope.payload !== 'string' || envelope.sha256 !== await digest(envelope.payload)) return null;
      const manifest = JSON.parse(envelope.payload);
      if (!validManifest(manifest)) return null;
      const refs = new Set<string>(manifest.inputDraft ? [manifest.inputDraft] : []);
      for (const entry of Object.values(manifest.projects)) {
        refs.add(entry.metadata); entry.views.forEach(hash => refs.add(hash));
      }
      return refs;
    } catch { return null; }
  }
  private async collect(retired: Set<string> | null) {
    if (!this.storage.remove || !retired?.size) return;
    // Reachability is decided by the complete, checksum-verified manifests,
    // not by rereading their immutable contents. Every retained hash is kept
    // even if its block later becomes unreadable. No legacy keys are visited.
    const first = await this.references(0), second = await this.references(1);
    if (!first || !second) return;
    for (const hash of retired) {
      if (first.has(hash) || second.has(hash)) continue;
      const cached = this.blocks.get(hash);
      if (cached !== undefined) this.hashes.delete(cached);
      this.blocks.delete(hash);
      this.verifiedHashes.delete(hash);
      try { await this.storage.remove(`${prefix}.block.${hash}`); }
      catch { /* Cleanup is best effort; a committed record remains successful. */ }
    }
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
    // v1 remains a read-only migration source. The first v2 manifest commits
    // only after every referenced block has been durably written and checked.
    const oldHead = await this.storage.get(`${legacyPrefix}.head`);
    if (oldHead !== null) {
      if (!['0', '1'].includes(oldHead)) throw new DeviceStorageError('旧版设备存储索引无法读取；原始记录保留。');
      const state = await this.slot(Number(oldHead), legacyPrefix) || await this.slot(1 - Number(oldHead), legacyPrefix);
      if (!state) throw new DeviceStorageError('旧版设备记录暂时无法读取；原始记录保留。');
      this.recoveryNotice = '旧版设备记录已读取；后续保存使用分块副本，原始记录保留。';
      return { state, active: 1 };
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
        const shadow = 1 - active;
        const retired = this.storage.remove ? await this.references(shadow) : null;
        const next = structuredClone(state);
        applyingMutation = true; change(next); applyingMutation = false;
        next.revision = state.revision + 1;
        if (!validState(next)) throw new DeviceStorageError('设备数据校验失败，未覆盖旧记录。');
        const projects: Record<string, { metadata: string; views: string[] }> = {};
        for (const [id, project] of Object.entries(next.projects)) {
          const { views, ...metadata } = project;
          const hashes = [];
          for (const view of views) hashes.push(await this.writeBlock(view));
          projects[id] = { metadata: await this.writeBlock(metadata), views: hashes };
        }
        const payload = JSON.stringify({ schema: 2, revision: next.revision, selected: next.selected, projects,
          inputDraft: next.inputDraft ? await this.writeBlock(next.inputDraft) : null });
        if (new TextEncoder().encode(payload).byteLength > maxBytes) throw new DeviceStorageError('设备索引已达本机保存上限，旧记录未被覆盖。');
        const key = `${prefix}.slot${shadow}`;
        const envelope = JSON.stringify({ schema: 2, payload, sha256: await digest(payload) });
        await this.storage.set(key, envelope);
        if (await this.storage.get(key) !== envelope) throw new Error('shadow verification');
        await this.storage.set(`${prefix}.head`, String(shadow));
        if (await this.storage.get(`${prefix}.head`) !== String(shadow)) throw new Error('commit verification');
        this.snapshotCache = { raw: envelope, state: next };
        await this.collect(retired);
        return structuredClone(next);
      } catch (error) {
        if (applyingMutation) throw error; // Business guards are not disk failures.
        if (error instanceof DeviceStorageError) throw error;
        throw new DeviceStorageError('未能可靠保存到本机；旧记录仍保留。请释放设备空间后重新保存，不会自动提交服务器。');
      }
    });
  }
}
