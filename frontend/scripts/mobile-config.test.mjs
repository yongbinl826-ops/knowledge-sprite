import test from 'node:test';
import assert from 'node:assert/strict';
import { validateApiBase, checkNativeConfig, scanAssetText, mobileDefines } from './mobile-config.mjs';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { build } from 'vite';
import { fileHashes, frontendSourceHashes, requireSameHashes } from './mobile-integrity.mjs';

test('release requires explicit public HTTPS origin and no credentials/path/query', () => {
  for (const value of [undefined, '', 'http://api.school.edu', 'https://localhost:8003',
    'https://127.0.0.1:8003', 'https://[::1]:8003', 'https://192.168.1.2', 'https://api.example.org',
    'https://localhost.', 'https://api.local.', 'https://*.school.edu', 'https://api.school.edu:0',
    'https://api.school.edu/api', 'https://a:b@api.school.edu', 'https://api.school.edu?token=secret', 'javascript:alert(1)']) {
    assert.throws(() => validateApiBase(value, 'release'));
  }
  assert.equal(validateApiBase('https://api.school.edu/', 'release'), 'https://api.school.edu');
});
test('development is finite loopback only, never a LAN wildcard', () => {
  assert.equal(validateApiBase('http://127.0.0.1:8003', 'debug'), 'http://127.0.0.1:8003');
  assert.equal(validateApiBase('http://localhost:8003', 'debug'), 'http://localhost:8003');
  assert.equal(validateApiBase('http://[::1]:8003', 'debug'), 'http://[::1]:8003');
  for (const value of ['http://0.0.0.0:8003', 'http://192.168.1.2', 'http://127.0.0.1.evil.org', 'file:///tmp/index.html']) {
    assert.throws(() => validateApiBase(value, 'debug'));
  }
});
const config = { appId: 'dev.knowledgeguide.sprite', webDir: 'dist-mobile', server: {
  hostname: 'localhost', androidScheme: 'https', cleartext: false },
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false } };
test('native release config rejects remote loading, arbitrary navigation and stale debug config', () => {
  checkNativeConfig(config, 'release');
  for (const change of [ { server: { ...config.server, url: 'https://remote.school.edu' } },
    { server: { ...config.server, allowNavigation: ['*'] } },
    { server: { ...config.server, cleartext: true } },
    { android: { ...config.android, allowMixedContent: true } },
    { android: { ...config.android, webContentsDebuggingEnabled: true } } ]) {
    assert.throws(() => checkNativeConfig({ ...config, ...change }, 'release'));
  }
});
test('asset scan returns rule IDs, never credential text; normal API names are not keys', () => {
  assert.deepEqual(scanAssetText('JSON.stringify({api_key: unavailable})'), []);
  assert.deepEqual(scanAssetText('-----BEGIN PRIVATE KEY----- synthetic'), ['private_key']);
  assert.deepEqual(scanAssetText(`api_key="${'a'.repeat(32)}"`), ['literal_api_credential']);
});
test('actual Vite production output preserves explicit debug permission while DEV remains false', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'knowledge-mobile-flags-'));
  const entry = path.join(dir, 'flags.js');
  await writeFile(entry, `export const dev=import.meta.env.DEV; export const debug=import.meta.env.DEV || import.meta.env.VITE_MOBILE_DEBUG_LOOPBACK==='true';`);
  try {
    for (const kind of ['debug', 'release']) {
      const base = kind === 'debug' ? 'http://127.0.0.1:8003' : 'https://api.school.edu';
      const result = await build({ configFile:false, root:dir, envDir:false, envPrefix:[], mode:'production',
        logLevel:'silent', define:mobileDefines(base,kind), build:{write:false,minify:false,
          lib:{entry,formats:['es']}} });
      const chunk = (Array.isArray(result) ? result[0] : result).output.find(item => item.type === 'chunk');
      const compiled = await import('data:text/javascript;base64,' + Buffer.from(chunk.code).toString('base64'));
      assert.equal(compiled.dev, false);
      assert.equal(compiled.debug, kind === 'debug');
      if (compiled.debug) assert.equal(validateApiBase('http://127.0.0.1:8003', 'debug'), 'http://127.0.0.1:8003');
      else assert.throws(() => validateApiBase('http://127.0.0.1:8003', 'release'));
    }
  } finally {
    assert(dir.startsWith(path.resolve(tmpdir()) + path.sep));
    await rm(dir, {recursive:true,force:true});
  }
});
test('receipt detects edited/new frontend source and unlisted packaged assets', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'knowledge-mobile-integrity-'));
  try {
    await mkdir(path.join(dir,'src')); await mkdir(path.join(dir,'public'));
    for (const file of ['src/a.ts','vite.config.ts','index.html','tsconfig.json']) await writeFile(path.join(dir,file),'baseline');
    const sources = await frontendSourceHashes(dir);
    await writeFile(path.join(dir,'src/a.ts'),'changed');
    const changed = await frontendSourceHashes(dir);
    assert.throws(() => requireSameHashes(changed,sources,'source_changed'));
    await writeFile(path.join(dir,'src/a.ts'),'baseline');
    await writeFile(path.join(dir,'src/b.ts'),'new');
    const added = await frontendSourceHashes(dir);
    assert.throws(() => requireSameHashes(added,sources,'source_added'));
    await writeFile(path.join(dir,'public/index.html'),'bundle');
    await writeFile(path.join(dir,'public/mobile-build.json'),'receipt');
    const assets = await fileHashes(path.join(dir,'public'),new Set(['mobile-build.json']));
    await writeFile(path.join(dir,'public/old.js'),'stale chunk');
    const extra = await fileHashes(path.join(dir,'public'),new Set(['mobile-build.json']));
    assert.throws(() => requireSameHashes(extra,assets,'unlisted_asset'));
  } finally {
    assert(dir.startsWith(path.resolve(tmpdir()) + path.sep));
    await rm(dir, {recursive:true,force:true});
  }
});
