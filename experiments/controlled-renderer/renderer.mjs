// Experimental bridge. stdin JSON lines: one audited-fixture request, then optional {"cancel":true}.
// No production import, network transport, remote HTML, storage state, or arbitrary script input.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import readline from 'node:readline';
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '../../frontend/package.json'));
const { chromium } = require('playwright');
const scenarios = new Set(['course', 'missing', 'post', 'navigate', 'guard', 'frame', 'wait']);
const origin = 'https://renderer.example.org';
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
const failure = message => Object.assign(new Error(message), { code: message });
let started = false, cancelled = false, activePage;
let inputBytes = 0, inputExceeded = false;
// Bound the stream before readline can buffer an unbounded unterminated line.
process.stdin.on('data', chunk => {
  inputBytes += Buffer.byteLength(chunk);
  if (inputBytes <= 300_000 || inputExceeded) return;
  inputExceeded = true;
  cancelled = true;
  if (started) activePage?.close().catch(() => {});
  else emit({ event: 'result', ok: false, status: 'input_byte_budget' });
  input.close();
  process.stdin.pause();
});
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  if (inputExceeded) return;
  let message;
  try { message = JSON.parse(line); } catch { emit({ event: 'result', ok: false, status: 'invalid_json' }); input.close(); return; }
  if (message.cancel === true) { cancelled = true; activePage?.close().catch(() => {}); return; }
  if (started) { cancelled = true; activePage?.close().catch(() => {}); return; }
  started = true;
  run(message).then(emit).catch(error => emit({ event: 'result', ok: false, status: error.code || 'bridge_error' })).finally(() => { input.close(); process.stdin.pause(); });
});

function validate(message) {
  if (message.mode !== 'audited_fixture_only') throw failure('remote_rendering_disabled');
  if (!scenarios.has(message.scenario) || message.entry_url !== `${origin}/course?scenario=${message.scenario}`) throw failure('unknown_audited_fixture');
  const limits = message.budgets || {};
  for (const [key, min, max] of [['max_resources', 1, 8], ['max_total_bytes', 1, 100000], ['timeout_ms', 50, 10000]]) {
    if (!Number.isInteger(limits[key]) || limits[key] < min || limits[key] > max) throw failure('invalid_budget');
  }
  if (!Array.isArray(message.resources) || message.resources.length > limits.max_resources) throw failure('resource_count_budget');
  const resources = new Map();
  let bytes = 0;
  for (const resource of message.resources) {
    const expectedURL = resource.fixture_file === 'course.html' ? message.entry_url : resource.fixture_file === 'course.js' ? `${origin}/course.js` : null;
    if (!expectedURL || resource.url !== expectedURL || resources.has(resource.url)) throw failure('unapproved_fixture_resource');
    const body = Buffer.from(resource.body_b64 || '', 'base64');
    const trusted = fs.readFileSync(path.join(here, 'fixtures', resource.fixture_file));
    if (!body.equals(trusted) || createHash('sha256').update(body).digest('hex') !== resource.sha256) throw failure('fixture_integrity_mismatch');
    const mime = resource.fixture_file === 'course.html' ? 'text/html' : 'application/javascript';
    if (resource.content_type !== mime) throw failure('unapproved_content_type');
    bytes += body.length;
    if (bytes > limits.max_total_bytes) throw failure('total_byte_budget');
    resources.set(resource.url, { body, mime });
  }
  if (!resources.has(message.entry_url)) throw failure('entry_resource_missing');
  return { resources, limits };
}

async function run(message) {
  const { resources, limits } = validate(message);
  let server, browser, context, timer, browserPid, browserExitObserved = false, result;
  const observed = [], blocked = [];
  let deadline = false, mainDocumentUsed = false, fulfilledBytes = 0;
  const stop = code => { blocked.push(code); activePage?.close().catch(() => {}); };
  try {
    if (cancelled) throw failure('cancelled');
    server = await chromium.launchServer({ channel: 'msedge', headless: true, timeout: 10000,
      args: ['--disable-background-networking', '--disable-component-update', '--no-default-browser-check', '--disable-sync'] });
    browserPid = server.process().pid;
    server.process().once('exit', () => { browserExitObserved = true; });
    browser = await chromium.connect(server.wsEndpoint());
    context = await browser.newContext({ offline: true, serviceWorkers: 'block', acceptDownloads: false });
    // Offline is not an OS-level network sandbox and does not establish UDP isolation.
    await context.routeWebSocket('**/*', async ws => { blocked.push('websocket'); await ws.close(); });
    await context.route('**/*', async route => {
      const request = route.request();
      let reason;
      if (request.method() !== 'GET') reason = 'non_get';
      else if (!['document', 'script', 'stylesheet', 'image', 'font', 'fetch', 'xhr'].includes(request.resourceType())) reason = 'forbidden_resource_type';
      else if (request.isNavigationRequest() && (mainDocumentUsed || request.url() !== message.entry_url || request.frame() !== activePage?.mainFrame())) reason = 'navigation_or_frame';
      else if (!resources.has(request.url())) reason = 'resource_not_preapproved';
      else if (observed.length >= limits.max_resources) reason = 'request_count_budget';
      if (reason) { await route.abort(); stop(reason); return; }
      const resource = resources.get(request.url());
      fulfilledBytes += resource.body.length;
      if (fulfilledBytes > limits.max_total_bytes) { await route.abort(); stop('fulfilled_byte_budget'); return; }
      if (request.isNavigationRequest()) mainDocumentUsed = true;
      observed.push({ url: request.url(), resource_type: request.resourceType(), bytes: resource.body.length });
      await route.fulfill({ status: 200, body: resource.body, contentType: resource.mime,
        headers: { 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'none'; img-src 'none'; connect-src 'self'; frame-src 'none'; worker-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'" } });
    });
    await context.addInitScript(() => {
      Object.defineProperty(window, '__fixtureBlocked', { value: [], writable: false });
      const deny = name => function () { window.__fixtureBlocked.push(name); throw new Error('disabled_' + name); };
      for (const name of ['Worker', 'SharedWorker', 'WebSocket', 'RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport']) {
        Object.defineProperty(window, name, { value: deny(name), configurable: false, writable: false });
      }
      Object.defineProperty(window, 'open', { value: deny('popup'), configurable: false, writable: false });
    });
    activePage = await context.newPage();
    context.on('page', page => { if (page !== activePage) { blocked.push('popup'); page.close().catch(() => {}); } });
    activePage.on('frameattached', () => stop('frame'));
    activePage.on('worker', worker => { worker.evaluate(() => self.close()).catch(() => {}); stop('worker'); });
    activePage.on('download', download => { download.cancel().catch(() => {}); stop('download'); });
    timer = setTimeout(() => { deadline = true; activePage?.close().catch(() => {}); }, limits.timeout_ms);
    emit({ event: 'ready', browser_pid: browserPid, remote_enabled: false });
    if (cancelled) throw failure('cancelled');
    await activePage.goto(message.entry_url, { waitUntil: 'domcontentloaded', timeout: limits.timeout_ms });
    await activePage.waitForFunction(() => window.__fixtureDone === true, undefined, { timeout: limits.timeout_ms });
    const guards = await activePage.evaluate(() => window.__fixtureBlocked);
    blocked.push(...guards);
    if (blocked.length) throw failure('forbidden_operation');
    const html = await activePage.content();
    if (Buffer.byteLength(html) > 100000) throw failure('output_byte_budget');
    result = { ok: true, status: 'fixture_rendered', html };
  } catch (error) {
    result = { ok: false, status: cancelled ? 'cancelled' : deadline ? 'timeout' : error.code || blocked[0] || 'render_failed' };
  } finally {
    clearTimeout(timer);
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await server?.close().catch(() => {});
    activePage = undefined;
  }
  return { event: 'result', ...result, fulfilled: observed, blocked, browser_pid: browserPid,
    cleanup: { context_closed: context ? context.pages().length === 0 : true, browser_exit_observed: browserExitObserved },
    isolation: { page_http: 'preapproved_offline_fulfill_only', remote_rendering: 'disabled', process_network_egress: 'unknown', webrtc_udp_egress: 'unknown', real_site_scripts: 'not_executed' } };
}
