/** Conditional reads never start work. ETags are scoped to this watcher and URL. */
export async function readSnapshot<T>(url: string, signal: AbortSignal, etag?: string): Promise<{ value: T | null; etag?: string }> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, 15_000);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: etag ? { 'If-None-Match': etag } : {} });
    if (response.status === 304 && etag) return { value: null, etag };
    if (!response.ok) throw new Error(`状态读取失败（HTTP ${response.status}）`);
    const value = await response.json() as T;
    return { value, etag: response.headers.get('ETag') || undefined };
  } finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}

export function snapshotPollDelay(background: boolean, unchanged: number, failures = 0): number {
  return Math.min(background ? 15_000 : 6_000, (background ? 3_000 : 1_500) * 2 ** Math.min(unchanged + failures, 3));
}
