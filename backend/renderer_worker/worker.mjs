// Production bridge: stdin supplies bytes fetched under Python Fetcher policy.
// There is deliberately no HTTP transport, fixture loader or network fallback here.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import readline from 'node:readline';
const require = createRequire(path.join(path.dirname(fileURLToPath(import.meta.url)), '../../frontend/package.json'));
const { chromium } = require('playwright');
const fail = code => Object.assign(new Error(code), { code });
let started = false, cancelled = false, activePage, inputBytes = 0, exceeded = false;
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
process.stdin.on('data', chunk => {
  inputBytes += chunk.length;
  if (inputBytes > 12_000_000 && !exceeded) {
    exceeded = true; cancelled = true; activePage?.close().catch(() => {});
    input.close(); process.stdin.pause();
    if (!started) process.stdout.write(JSON.stringify({ status: 'render_input_budget' }) + '\n');
  }
});
input.on('line', line => {
  if (exceeded) return;
  let message;
  try { message = JSON.parse(line); } catch { finish({ status: 'render_invalid_json' }); return; }
  if (message.cancel === true || started) { cancelled = true; activePage?.close().catch(() => {}); return; }
  started = true;
  run(message).then(finish).catch(error => finish({ status: error.code || 'render_failed' }));
});
function finish(result) {
  process.stdout.write(JSON.stringify(result) + '\n');
  input.close(); process.stdin.pause();
}
function validate(message) {
  const origin = new URL(message.entry_url).origin;
  const safe = (raw, kind) => {
    const url = new URL(raw);
    const allowedAsset = ['script', 'stylesheet'].includes(kind) && url.protocol === 'https:' && message.asset_hosts?.includes(url.hostname);
    if (!['http:', 'https:'].includes(url.protocol) || (url.origin !== origin && !allowedAsset) || url.username || url.password || url.hash) throw fail('render_scope_blocked');
    return url.href;
  };
  if (safe(message.entry_url) !== message.entry_url) throw fail('render_invalid_entry');
  for (const [key, min, max] of [['max_dom_bytes', 1, 2_000_000], ['max_total_bytes', 1, 8_000_000], ['settle_ms', 0, 2000], ['timeout_ms', 1000, 120000]]) {
    if (!Number.isInteger(message[key]) || message[key] < min || message[key] > max) throw fail('render_invalid_budget');
  }
  if (!Array.isArray(message.resources) || message.resources.length < 1 || message.resources.length > 21) throw fail('render_resource_budget');
  if (!Array.isArray(message.inline_hashes) || message.inline_hashes.some(v => !/^sha256-[A-Za-z0-9+/]{43}=$/.test(v))) throw fail('render_invalid_hash');
  const resources = new Map(), aliases = new Map();
  let bytes = 0, documents = 0;
  for (const entry of message.resources) {
    const url = safe(entry.url, entry.kind), requested = safe(entry.requested_url, entry.kind);
    if (new URL(url).origin !== new URL(requested).origin) throw fail('render_redirect_scope');
    if (!['document', 'script', 'stylesheet', 'data'].includes(entry.kind)) throw fail('render_invalid_kind');
    const allowed = entry.kind === 'document' ? ['text/html'] : entry.kind === 'stylesheet' ? ['text/css'] : entry.kind === 'data' ? ['text/plain', 'text/markdown', 'text/x-markdown', 'application/json'] : ['text/javascript', 'application/javascript', 'application/ecmascript', 'text/ecmascript'];
    if (!allowed.includes(entry.mime) || typeof entry.body_b64 !== 'string' || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(entry.body_b64)) throw fail('render_invalid_resource');
    const body = Buffer.from(entry.body_b64, 'base64');
    bytes += body.length;
    if (bytes > message.max_total_bytes) throw fail('render_byte_budget');
    if (resources.has(url) && (!resources.get(url).body.equals(body) || resources.get(url).kind !== entry.kind)) throw fail('render_ambiguous_resource');
    if (entry.kind === 'document') { documents++; if (url !== message.entry_url || requested !== url) throw fail('render_invalid_document'); }
    resources.set(url, { ...entry, body });
    if (requested !== url) {
      if (aliases.has(requested) && aliases.get(requested) !== url) throw fail('render_ambiguous_redirect');
      aliases.set(requested, url);
    }
  }
  if (documents !== 1 || !resources.has(message.entry_url)) throw fail('render_invalid_document');
  for (const alias of aliases.keys()) if (resources.has(alias)) throw fail('render_ambiguous_redirect');
  return { resources, aliases };
}
async function bounded(promise, ms) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(fail('cleanup_timeout')), ms); })]); }
  finally { clearTimeout(timer); }
}
async function run(message) {
  const { resources, aliases } = validate(message);
  let server, browser, context, timer, expired = false, mainUsed = false, edgeExit = null, result;
  let fulfilledBytes = 0, fatalBlocked = false;
  const blocked = [], fulfilled = [];
  // Optional integrations observed on MIT's public pages are always denied.
  // Their omission does not establish failure of core course content. Unknown
  // scripts, data and CSP violations remain fatal; the original HTML is replayed unchanged.
  const optionalIntegration = raw => {
    try {
      const target = new URL(raw);
      return new URL(message.entry_url).hostname === 'ocw.mit.edu' && target.protocol === 'https:' &&
        ((target.hostname === 'w.appzi.io' && target.pathname === '/w.js') ||
         (target.hostname === 'www.googletagmanager.com' && ['/gtm.js', '/gtag/js'].includes(target.pathname)));
    } catch { return false; }
  };
  const record = (reason, url = '', fatal = true, method = '', kind = '') => {
    if (blocked.length < 100) blocked.push({ reason, url, method, kind, fatal });
    if (fatal) fatalBlocked = true;
  };
  timer = setTimeout(() => { expired = true; activePage?.close().catch(() => {}); }, message.timeout_ms);
  try {
    if (cancelled) throw fail('cancelled');
    server = await chromium.launchServer({ channel: 'msedge', headless: true, timeout: Math.min(message.timeout_ms, 10000),
      args: ['--disable-background-networking', '--disable-component-update', '--no-default-browser-check', '--disable-sync'] });
    edgeExit = false;
    server.process().once('exit', () => { edgeExit = true; });
    browser = await chromium.connect(server.wsEndpoint());
    context = await browser.newContext({ offline: true, serviceWorkers: 'block', acceptDownloads: false });
    await context.exposeBinding('__recordRenderBlocked', (_, reason, url, fatal) => record(String(reason).slice(0, 100), String(url).slice(0, 2048), fatal !== false));
    await context.routeWebSocket('**/*', async socket => { record('websocket'); await socket.close(); });
    // No route.fetch(), continue(), HTTP client or omitted-route network path.
    await context.route('**/*', async route => {
      const req = route.request(), url = req.url(), kind = req.resourceType();
      const passive = ['image', 'font', 'media'].includes(kind);
      let reason;
      if (req.method() !== 'GET') reason = 'non_get';
      else if (req.isNavigationRequest() && (mainUsed || url !== message.entry_url || req.frame() !== activePage?.mainFrame())) reason = 'navigation_or_frame';
      else if (kind === 'script' && optionalIntegration(url)) reason = 'optional_integration_blocked';
      else if (!['document', 'script', 'stylesheet', 'fetch', 'xhr'].includes(kind)) reason = 'forbidden_resource_type';
      else if (!resources.has(url) && !aliases.has(url)) reason = 'resource_not_preapproved';
      else if (fulfilled.length >= 42) reason = 'render_local_request_budget';
      else if (resources.has(url) && resources.get(url).kind !== (['fetch', 'xhr'].includes(kind) ? 'data' : kind)) reason = 'resource_kind_mismatch';
      if (reason) { record(reason, url, !passive && reason !== 'optional_integration_blocked', req.method(), kind); await route.abort(); return; }
      if (aliases.has(url)) {
        fulfilled.push({ url, redirect_to: aliases.get(url), bytes: 0, kind });
        await route.fulfill({ status: 302, headers: { location: aliases.get(url), 'cache-control': 'no-store' }, body: '' }); return;
      }
      const entry = resources.get(url);
      fulfilledBytes += entry.body.length;
      if (fulfilledBytes > message.max_total_bytes) { record('render_local_byte_budget', url); await route.abort(); return; }
      if (req.isNavigationRequest()) mainUsed = true;
      fulfilled.push({ url, kind, bytes: entry.body.length });
      const hashes = message.inline_hashes.map(value => `'${value}'`).join(' ');
      const assetOrigins = [...new Set([...resources.values()].filter(r => ['script', 'stylesheet'].includes(r.kind)).map(r => new URL(r.url).origin))].join(' ');
      // Exact optional script paths reach the route guard so it can inspect the
      // real method/type/URL before aborting. No optional bytes are fulfilled or
      // fetched. Unknown paths and every non-script use remain fatal. An original
      // CSP is still intersected below, never relaxed or reclassified by origin.
      const optionalScriptPaths = new URL(message.entry_url).hostname === 'ocw.mit.edu'
        ? 'https://w.appzi.io/w.js https://www.googletagmanager.com/gtm.js https://www.googletagmanager.com/gtag/js' : '';
      const policy = `default-src 'none'; script-src 'self' ${hashes} ${assetOrigins} ${optionalScriptPaths}; style-src 'self' 'unsafe-inline' ${assetOrigins}; img-src 'none'; font-src 'none'; connect-src 'self'; frame-src 'none'; worker-src 'none'; media-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'`;
      const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };
      if (kind === 'document') headers['content-security-policy'] = entry.csp ? policy + ', ' + entry.csp : policy;
      await route.fulfill({ status: 200, body: entry.body, contentType: entry.mime, headers });
    });
    await context.addInitScript(() => {
      const record = (reason, url = '', fatal = true) => window.__recordRenderBlocked(reason, url, fatal).catch(() => {});
      addEventListener('securitypolicyviolation', event => record('csp_' + event.effectiveDirective, event.blockedURI, !['img-src', 'font-src', 'media-src', 'style-src-attr'].includes(event.effectiveDirective)));
      const deny = name => function () { record(name); throw new Error('disabled_' + name); };
      for (const name of ['Worker', 'SharedWorker', 'WebSocket', 'RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport', 'open']) {
        Object.defineProperty(window, name, { value: deny(name), configurable: false, writable: false });
      }
      Object.defineProperty(navigator, 'sendBeacon', { value: deny('sendBeacon'), configurable: false, writable: false });
    });
    activePage = await context.newPage();
    context.on('page', page => { if (page !== activePage) { record('popup'); page.close().catch(() => {}); } });
    activePage.on('frameattached', () => { record('frame'); activePage.close().catch(() => {}); });
    activePage.on('worker', () => { record('worker'); activePage.close().catch(() => {}); });
    activePage.on('download', download => { record('download'); download.cancel().catch(() => {}); });
    process.stdout.write(JSON.stringify({ event: 'ready', edge_pid: server.process().pid }) + '\n');
    if (cancelled || expired) throw fail(cancelled ? 'cancelled' : 'render_timeout');
    await activePage.goto(message.entry_url, { waitUntil: 'domcontentloaded', timeout: message.timeout_ms });
    await activePage.waitForTimeout(message.settle_ms);
    if (cancelled || expired) throw fail(cancelled ? 'cancelled' : 'render_timeout');
    if (fatalBlocked) throw fail('render_dependency_blocked');
    const html = await activePage.content();
    if (Buffer.byteLength(html) > message.max_dom_bytes) throw fail('render_output_budget');
    result = { status: 'rendered', html };
  } catch (error) {
    result = { status: cancelled ? 'cancelled' : expired ? 'render_timeout' : error.code || (fatalBlocked ? 'render_dependency_blocked' : 'render_failed') };
  } finally {
    clearTimeout(timer);
    try { if (context) await bounded(context.close(), 1000); } catch {}
    try { if (browser) await bounded(browser.close(), 1000); } catch {}
    try { if (server) await bounded(server.close(), 1500); } catch {
      try { await bounded(server.kill(), 1500); } catch {}
    }
    activePage = undefined;
    // Remain owned by the parent when Edge cleanup is unresolved; its bounded
    // cancellation grace then kills the still-owned Node process tree.
    if (server && !edgeExit) await new Promise(() => {});
  }
  return { ...result, blocked_requests: blocked, fulfilled_requests: fulfilled,
    edge_main_exit_observed: edgeExit, all_descendant_processes_exited: 'unknown' };
}
