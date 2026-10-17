export class ApiError extends Error {
  constructor(message: string, public code: 'timeout' | 'http' | 'network') { super(message); this.name = 'ApiError'; }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = window.setTimeout(() => { timedOut = true; abort(); }, 15_000);
  try {
    const response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      throw new ApiError(detail || (response.status === 422 ? '输入格式不正确，请检查知识点和可选条件。' : `服务请求失败（HTTP ${response.status}）。请确认后端正在运行。`), 'http');
    }
    if (!body) throw new Error('服务未返回有效数据，请检查后端连接。');
    return body as T;
  } catch (error) {
    if (options.signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    if (timedOut) throw new ApiError('请求超过 15 秒未返回，请检查连接后重试。', 'timeout');
    if (error instanceof TypeError) throw new ApiError('网络连接失败，请检查后端连接。', 'network');
    throw error instanceof Error ? error : new ApiError('网络连接失败，请重试。', 'network');
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export function externalUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; }
  catch { return undefined; }
}

export const statusNames: Record<string, string> = {
  queued: '等待执行', running: '正在查找', completed: '检索完成', partial: '部分完成',
  failed: '检索失败', interrupted: '任务已中断', cancelled: '任务已取消', unconfigured: '未配置', configured: '已配置，待验证',
  available: '可用', fault: '故障', disabled: '未启用', unavailable: '不可用',
};
export const platformNames: Record<string, string> = { bilibili: 'B站', icourse163: '中国大学 MOOC', xuetangx: '学堂在线', general: '其他网站', other: '其他网站' };
export function dateLabel(value: string | null | undefined): string {
  if (!value) return '未知';
  const date = new Date(value);
  // A policy review date does not establish a time of day.
  if (!Number.isNaN(date.getTime()) && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return Number.isNaN(date.getTime()) ? '未知' : date.toLocaleString('zh-CN', { hour12: false });
}
