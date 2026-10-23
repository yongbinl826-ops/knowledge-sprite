import { isIP } from 'node:net';

export const APP_ID = 'dev.knowledgeguide.sprite';
export const APP_NAME = '项目制学习引导小精灵';
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

export function validateApiBase(raw, kind) {
  if (!['debug', 'release'].includes(kind)) throw new Error('mobile_kind_invalid');
  if (!raw || typeof raw !== 'string') throw new Error('mobile_api_base_required');
  let url;
  try { url = new URL(raw); } catch { throw new Error('mobile_api_base_invalid'); }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || url.port === '0') {
    throw new Error('mobile_api_base_must_be_origin');
  }
  if (kind === 'debug') {
    if (!LOOPBACK.has(url.hostname) || !['http:', 'https:'].includes(url.protocol)) {
      throw new Error('mobile_debug_requires_loopback');
    }
  } else {
    const host = url.hostname.toLowerCase();
    const labels = host.split('.');
    const domainShape = host.length <= 253 && labels.length >= 2 &&
      labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label));
    if (url.protocol !== 'https:' || LOOPBACK.has(host) || isIP(host.replace(/^\[|\]$/g, '')) ||
        !domainShape || /(?:^|\.)(?:localhost|local|lan|internal|invalid|test|example)$/.test(host) ||
        host.endsWith('.home.arpa') ||
        /(?:^|\.)example\.(?:com|net|org)$/.test(host)) {
      throw new Error('mobile_release_requires_public_https_domain');
    }
  }
  return url.origin;
}

export function checkNativeConfig(config, kind) {
  if (config.appId !== APP_ID || config.webDir !== 'dist-mobile') throw new Error('mobile_native_identity_mismatch');
  const server = config.server || {};
  if ('url' in server || 'allowNavigation' in server || server.cleartext !== false ||
      server.androidScheme !== 'https' || server.hostname !== 'localhost') {
    throw new Error('mobile_remote_webview_or_network_override_forbidden');
  }
  if (config.android?.allowMixedContent !== (kind === 'debug')) throw new Error('mobile_mixed_content_mode_mismatch');
  if (config.android?.webContentsDebuggingEnabled !== false) throw new Error('mobile_webview_debug_override_forbidden');
}

export function mobileDefines(apiBase, kind) {
  const base = validateApiBase(apiBase, kind);
  // Vite production builds have DEV=false even for an Android debug variant.
  return { 'import.meta.env.VITE_DEVICE_MODE': JSON.stringify('true'),
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(base),
    'import.meta.env.VITE_MOBILE_DEBUG_LOOPBACK': JSON.stringify(kind === 'debug' ? 'true' : 'false') };
}

export function scanAssetText(text) {
  const rules = [
    ['private_key', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
    ['provider_key', /\bsk-[A-Za-z0-9_-]{20,}\b/],
    ['google_key', /\bAIza[0-9A-Za-z_-]{30,}\b/],
    ['literal_api_credential', /(?:api[_-]?key|client[_-]?secret|authorization)\s*[:=]\s*["'](?:Bearer\s+)?[A-Za-z0-9_-]{24,}["']/i],
  ];
  return rules.filter(([, expression]) => expression.test(text)).map(([name]) => name);
}
