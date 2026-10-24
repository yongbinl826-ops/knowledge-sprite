// A stream only reads saved snapshots. Falling back never creates or retries a search.
export function openSnapshotStream<T>({ url, signal, onSnapshot, onComplete, onFallback, reconnectDelays = [1000, 3000] }: {
  url: string; signal: AbortSignal;
  onSnapshot: (snapshot: T) => void;
  onComplete: (snapshot?: T) => void;
  onFallback: () => void;
  reconnectDelays?: number[];
}): () => void {
  let source: EventSource | null = null;
  let stopped = false;
  let dataTimer: ReturnType<typeof setTimeout> | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let reconnects = 0;
  const close = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(dataTimer);
    clearTimeout(reconnectTimer);
    source?.close();
    signal.removeEventListener('abort', close);
  };
  const fallback = () => {
    if (stopped || signal.aborted) return;
    close(); onFallback();
  };
  const retry = () => {
    if (stopped || signal.aborted) return;
    clearTimeout(dataTimer); source?.close(); source = null;
    if (reconnects >= reconnectDelays.length) { fallback(); return; }
    reconnectTimer = setTimeout(connect, reconnectDelays[reconnects++]);
  };
  const awaitData = (milliseconds: number) => {
    clearTimeout(dataTimer);
    if (!stopped && !signal.aborted) dataTimer = setTimeout(retry, milliseconds);
  };
  if (signal.aborted) return close;
  signal.addEventListener('abort', close, { once: true });
  if (typeof EventSource === 'undefined') { fallback(); return close; }
  function connect() {
   if (stopped || signal.aborted) return;
   try {
    const connection = new EventSource(url);
    source = connection;
    // An open connection can still buffer every frame. Require actual data,
    // then allow quiet catalog work before falling back to saved-state reads.
    // SSE heartbeat comments do not reach EventSource listeners.
    awaitData(15_000);
    connection.addEventListener('snapshot', event => {
      if (stopped || signal.aborted || source !== connection) return;
      try {
        onSnapshot(JSON.parse((event as MessageEvent<string>).data) as T);
        awaitData(60_000);
      }
      catch { fallback(); }
    });
    connection.addEventListener('complete', event => {
      if (stopped || signal.aborted || source !== connection) return;
      try {
        const data = (event as MessageEvent<string>).data;
        const snapshot = data ? JSON.parse(data) as T : undefined;
        // Validate/apply the final frame before closing. Malformed data uses a fresh read.
        onComplete(snapshot);
        close();
      } catch { fallback(); }
    });
    connection.addEventListener('heartbeat', () => { if (source === connection) awaitData(60_000); });
    connection.addEventListener('error', () => { if (source === connection) retry(); });
   } catch { retry(); }
  }
  connect();
  return close;
}
