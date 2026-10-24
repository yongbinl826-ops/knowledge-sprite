/** Merge edits while preserving every caller's durable-save acknowledgement. */
export class DraftWriter<T> {
  private pending = new Map<string, { change: (state: T) => void; waiters: { resolve: () => void; reject: (error: unknown) => void }[] }>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private running: Promise<void> | undefined;
  constructor(private readonly commit: (change: (state: T) => void) => Promise<unknown>, private readonly delay = 200) {}
  save(key: string, change: (state: T) => void): Promise<void> {
    clearTimeout(this.timer);
    const entry = this.pending.get(key) || { change, waiters: [] };
    entry.change = change; this.pending.set(key, entry);
    const result = new Promise<void>((resolve, reject) => entry.waiters.push({ resolve, reject }));
    this.timer = setTimeout(() => { void this.flush().catch(() => {}); }, this.delay);
    return result;
  }
  async flush(): Promise<void> {
    clearTimeout(this.timer);
    if (this.running) { await this.running; if (this.pending.size) await this.flush(); return; }
    if (!this.pending.size) return;
    const batch = [...this.pending.entries()]; this.pending.clear();
    const entries = batch.map(([, entry]) => entry);
    this.running = (async () => {
      try { await this.commit(state => entries.forEach(entry => entry.change(state))); entries.forEach(entry => entry.waiters.forEach(waiter => waiter.resolve())); }
      catch (error) {
        // Keep the latest unsaved values for the next explicit flush/edit. A
        // failed local save must not make navigation treat the draft as saved.
        for (const [key, entry] of batch) if (!this.pending.has(key)) this.pending.set(key, { change: entry.change, waiters: [] });
        entries.forEach(entry => entry.waiters.forEach(waiter => waiter.reject(error))); throw error;
      }
    })();
    try { await this.running; } finally { this.running = undefined; }
    if (this.pending.size) await this.flush();
  }
}
