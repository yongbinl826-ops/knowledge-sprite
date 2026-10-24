// A stream only reads saved snapshots. Falling back never creates or retries a search.
export function openSnapshotStream<T>({ url, signal, onSnapshot, onComplete, onFallback }: {
  url: string; signal: AbortSignal;
  onSnapshot: (snapshot: T) => void;
  onComplete: (snapshot?: T) => void;
  onFallback: () => void;
}): () => void {
  let source: EventSource | null = null;
  let stopped = false;
  let dataTimer: ReturnType<typeof setTimeout> | undefined;
  const close = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(dataTimer);
    source?.close();
    signal.removeEventListener('abort', close);
  };
  const fallback = () => {
    if (stopped || signal.aborted) return;
    close(); onFallback();
  };
  const awaitData = (milliseconds: number) => {
    clearTimeout(dataTimer);
    if (!stopped && !signal.aborted) dataTimer = setTimeout(fallback, milliseconds);
  };
  if (signal.aborted) return close;
  signal.addEventListener('abort', close, { once: true });
  if (typeof EventSource === 'undefined') { fallback(); return close; }
  try {
    source = new EventSource(url);
    // An open connection can still buffer every frame. Require actual data,
    // then allow quiet catalog work before falling back to saved-state reads.
    // SSE heartbeat comments do not reach EventSource listeners.
    awaitData(15_000);
    source.addEventListener('snapshot', event => {
      if (stopped || signal.aborted) return;
      try {
        onSnapshot(JSON.parse((event as MessageEvent<string>).data) as T);
        awaitData(60_000);
      }
      catch { fallback(); }
    });
    source.addEventListener('complete', event => {
      if (stopped || signal.aborted) return;
      try {
        const data = (event as MessageEvent<string>).data;
        const snapshot = data ? JSON.parse(data) as T : undefined;
        // Validate/apply the final frame before closing. Malformed data uses a fresh read.
        onComplete(snapshot);
        close();
      } catch { fallback(); }
    });
    source.addEventListener('error', fallback);
  } catch { fallback(); }
  return close;
}
