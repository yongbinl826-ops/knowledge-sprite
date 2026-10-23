// Build local packaged assets only. No environment file or remote WebView URL.
import { build } from 'vite';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { APP_ID, validateApiBase, checkNativeConfig, scanAssetText, mobileDefines } from './mobile-config.mjs';
import { sha256 as hash, walkFiles, fileHashes, frontendSourceHashes, requireSameHashes } from './mobile-integrity.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const kind = args.includes('--debug') ? 'debug' : 'release';
const raw = args.includes('--api-base') ? args[args.indexOf('--api-base') + 1] : process.env.VITE_API_BASE_URL;
function run(relative, args, env = process.env) {
  const result = spawnSync(process.execPath, [path.join(root, relative), ...args], { cwd: root, env, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`mobile_command_failed:${path.basename(relative)}:${result.status}`);
}
try {
  // Validate first: missing release deployment input cannot build a misleading package.
  const apiBase = validateApiBase(raw, kind);
  const sourceFiles = await frontendSourceHashes(root);
  run('node_modules/typescript/bin/tsc', ['-b']);
  await build({
    root, configFile: path.join(root, 'vite.config.ts'), envDir: false, envPrefix: [],
    mode: 'production', build: { outDir: 'dist-mobile' },
    define: mobileDefines(apiBase, kind),
  });
  run('node_modules/@capacitor/cli/bin/capacitor', ['sync', 'android'], { ...process.env, MOBILE_BUILD_KIND: kind });
  const nativePublic = path.join(root, 'android/app/src/main/assets/public');
  // Include Capacitor's generated cordova bridge stubs, too. The eventual
  // public directory must have exactly this list plus the receipt itself.
  const assets = await fileHashes(nativePublic, new Set(['mobile-build.json']));
  if (!assets['index.html']) throw new Error('mobile_packaged_index_missing');
  for (const file of await walkFiles(nativePublic)) {
    const bytes = await readFile(file);
    const findings = scanAssetText(bytes.toString('utf8'));
    if (findings.length) throw new Error(`mobile_asset_secret_pattern:${path.relative(root, file)}:${findings.join(',')}`);
  }
  requireSameHashes(await frontendSourceHashes(root), sourceFiles, 'mobile_sources_changed_during_build');
  const receipt = { schema: 'mobile-local-assets-v1', kind, appId: APP_ID, apiBase,
    builtAt: new Date().toISOString(), releaseEligible: kind === 'release', debugLoopback: kind === 'debug', sourceFiles,
    packageLockSha256: hash(await readFile(path.join(root, 'package-lock.json'))),
    capacitorConfigSha256: hash(await readFile(path.join(root, 'capacitor.config.ts'))), assets,
    sourceScope: 'bundled_local_assets; API availability/TLS/device behavior not verified by build' };
  await writeFile(path.join(root, 'dist-mobile/mobile-build.json'), JSON.stringify(receipt, null, 2) + '\n');
  await writeFile(path.join(nativePublic, 'mobile-build.json'), JSON.stringify(receipt, null, 2) + '\n');
  const nativeConfig = JSON.parse(await readFile(path.join(root, 'android/app/src/main/assets/capacitor.config.json'), 'utf8'));
  checkNativeConfig(nativeConfig, kind);
  console.log(JSON.stringify({ status: 'prepared', kind, apiBase, localAssetFiles: Object.keys(assets).length,
    releaseEligible: receipt.releaseEligible, apkCompiled: false, installed: false }));
} catch (error) {
  // Messages contain fixed validation codes or public file paths, never rejected secrets.
  console.error(error instanceof Error ? error.message : 'mobile_preparation_failed');
  process.exitCode = 2;
}
