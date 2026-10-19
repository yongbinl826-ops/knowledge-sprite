// A stream only reads saved snapshots. Falling back never creates or retries a search.
export function openSnapshotStream<T>({ url, signal, onSnapshot, onComplete, onFallback }: {
  url: string; signal: AbortSignal;
  onSnapshot: (snapshot: T) => void;
  onComplete: (snapshot?: T) => void;
  onFallback: () => void;
}): () => void {
  let source: EventSource | null = null;
  let stopped = false;
  let openingTimer: ReturnType<typeof setTimeout> | undefined;
  const close = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(openingTimer);
    source?.close();
    signal.removeEventListener('abort', close);
  };
  const fallback = () => {
    if (stopped || signal.aborted) return;
    close(); onFallback();
  };
  if (signal.aborted) return close;
  signal.addEventListener('abort', close, { once: true });
  if (typeof EventSource === 'undefined') { fallback(); return close; }
  try {
    source = new EventSource(url);
    openingTimer = setTimeout(fallback, 15_000);
    source.addEventListener('open', () => clearTimeout(openingTimer));
    source.addEventListener('snapshot', event => {
      if (stopped || signal.aborted) return;
      try { onSnapshot(JSON.parse((event as MessageEvent<string>).data) as T); }
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
