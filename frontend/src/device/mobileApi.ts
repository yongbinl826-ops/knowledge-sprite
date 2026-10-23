import type { CoursePage, MobileTask, TaskTicket } from './deviceTypes';

export const deviceDevelopment = (development: boolean, explicitDebugLoopback?: string) => development || explicitDebugLoopback === 'true';
export function mobileApiBase(value: string | undefined, development: boolean, origin?: string): string {
  const url = new URL(value || (development ? origin || '' : ''));
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || (url.protocol !== 'https:' && !(development && loopback && url.protocol === 'http:'))) {
    throw new Error('设备服务地址必须使用 HTTPS；开发时仅允许明确的本机回环地址。');
  }
  return url.href.replace(/\/$/, '');
}
export class MobileHttpError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfterMs = 1500) { super(message); this.name = 'MobileHttpError'; }
}
export function retryAfter(header: string | null, now = Date.now()): number {
  const seconds = header === null ? NaN : Number(header);
  const delay = Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : header ? Date.parse(header) - now : 1500;
  return Math.max(1500, Number.isFinite(delay) ? Math.min(delay, 2 * 60 * 60 * 1000) : 1500);
}
export class MobileApi {
  // Native WebView fetch must retain the Window receiver, unlike Node's fetch.
  constructor(readonly base: string, private readonly transport: typeof fetch = (input, init) => globalThis.fetch(input, init)) {}
  private async request<T>(path: string, options: RequestInit, signal?: AbortSignal): Promise<T> {
    if (!this.base) throw new Error('尚未配置安全的设备服务地址。');
    const controller = new AbortController(); const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    const timer = setTimeout(abort, 15000);
    try {
      const response = await this.transport(`${this.base}${path}`, { ...options, signal: controller.signal, credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new MobileHttpError(typeof body?.detail === 'string' ? body.detail : body?.detail?.message || `服务暂不可用（HTTP ${response.status}）`, response.status, retryAfter(response.headers.get('Retry-After')));
      if (!body) throw new Error('服务响应无法读取；已保留本机记录。');
      return body;
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
  task(ticket: TaskTicket, method: 'GET' | 'POST', signal?: AbortSignal): Promise<MobileTask> {
    return this.request(`/api/mobile/tasks/${encodeURIComponent(ticket.id)}`, { method,
      headers: { Authorization: `Bearer ${ticket.capability}`, ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      ...(method === 'POST' ? { body: ticket.body } : {}) }, signal);
  }
  cancel(ticket: TaskTicket, signal?: AbortSignal): Promise<MobileTask> {
    return this.request(`/api/mobile/tasks/${encodeURIComponent(ticket.id)}/cancel`, { method: 'POST', headers: { Authorization: `Bearer ${ticket.capability}` } }, signal);
  }
  courses(query: string, platform: string, offset: number, signal?: AbortSignal) {
    const parameters = new URLSearchParams({ query, offset: String(offset), limit: '12' });
    if (platform) parameters.set('platform', platform);
    return this.request<CoursePage>(`/api/mobile/courses?${parameters}`, { method: 'GET' }, signal);
  }
  capabilities(signal?: AbortSignal) { return this.request<import('../types').Capabilities>('/api/capabilities', { method: 'GET' }, signal); }
}
export function createTicket(projectId: string, version: number, body: import('./deviceTypes').MobileTaskBody, now = Date.now()): TaskTicket {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const capability = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return { schema: 1, id: crypto.randomUUID(), capability, body: JSON.stringify(body), projectId, version,
    createdAt: new Date(now).toISOString(), expiresAt: new Date(now + 2 * 60 * 60 * 1000).toISOString(), phase: 'prepared' };
}
