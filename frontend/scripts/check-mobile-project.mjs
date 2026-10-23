// Static project/asset checks; no SDK, external requests or signing operation.
import { readFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { APP_NAME, checkNativeConfig, validateApiBase, scanAssetText } from './mobile-config.mjs';
import { fileHashes, frontendSourceHashes, requireSameHashes } from './mobile-integrity.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const text = relative => readFile(path.join(root, relative), 'utf8');
async function walk(dir) {
  const paths = [];
  for (const item of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, item.name);
    if (item.isDirectory()) paths.push(...await walk(file)); else paths.push(file);
  }
  return paths;
}
try {
  const main = await text('android/app/src/main/AndroidManifest.xml');
  for (const attribute of ['allowBackup="false"', 'fullBackupContent="@xml/backup_rules"',
    'dataExtractionRules="@xml/data_extraction_rules"', 'usesCleartextTraffic="false"',
    'networkSecurityConfig="@xml/network_security_config"']) assert(main.includes(attribute), attribute);
  assert.equal([...main.matchAll(/<uses-permission\b/g)].length, 1, 'only INTERNET permission');
  assert(main.includes('android.permission.INTERNET'));
  assert(!main.includes('android:debuggable="true"'));
  const domains = ['root','file','database','sharedpref','external','device_root','device_file','device_database','device_sharedpref'];
  const backup = await text('android/app/src/main/res/xml/backup_rules.xml');
  const extraction = await text('android/app/src/main/res/xml/data_extraction_rules.xml');
  for (const domain of domains) {
    assert(backup.includes(`domain="${domain}" path="."`));
    assert.equal(extraction.split(`domain="${domain}" path="."`).length - 1, 3);
  }
  const network = await text('android/app/src/main/res/xml/network_security_config.xml');
  assert(network.includes('cleartextTrafficPermitted="false"') && !network.includes('cleartextTrafficPermitted="true"'));
  const debug = await text('android/app/src/debug/res/xml/network_security_config_debug.xml');
  assert.deepEqual([...debug.matchAll(/<domain includeSubdomains="false">([^<]+)<\/domain>/g)].map(m => m[1]), ['localhost','127.0.0.1','::1']);
  const gradle = await text('android/app/build.gradle');
  assert.equal(gradle.split('signingConfig null').length - 1, 2);
  assert(gradle.includes("apply from: 'mobile-release-gate.gradle'"));
  const variables = await text('android/variables.gradle');
  assert(/minSdkVersion\s*=\s*24/.test(variables) && /compileSdkVersion\s*=\s*36/.test(variables) && /targetSdkVersion\s*=\s*36/.test(variables));
  const config = JSON.parse(await text('android/app/src/main/assets/capacitor.config.json'));
  assert.equal(config.appName, APP_NAME);
  const labels = await text('android/app/src/main/res/values/strings.xml');
  for (const name of ['app_name', 'title_activity_main']) assert(labels.includes(`<string name="${name}">${APP_NAME}</string>`));
  const receipt = JSON.parse(await text('android/app/src/main/assets/public/mobile-build.json'));
  assert(receipt.assets?.['index.html'], 'packaged index is required');
  assert.equal(receipt.debugLoopback, receipt.kind === 'debug');
  validateApiBase(receipt.apiBase, receipt.kind);
  checkNativeConfig(config, receipt.kind);
  assert.equal(receipt.packageLockSha256, hash(await readFile(path.join(root,'package-lock.json'))));
  assert.equal(receipt.capacitorConfigSha256, hash(await readFile(path.join(root,'capacitor.config.ts'))));
  requireSameHashes(await frontendSourceHashes(root), receipt.sourceFiles, 'mobile_source_receipt_mismatch');
  requireSameHashes(await fileHashes(path.join(root, 'android/app/src/main/assets/public'), new Set(['mobile-build.json'])),
    receipt.assets, 'mobile_asset_receipt_mismatch');
  for (const [name, expected] of Object.entries(receipt.assets)) {
    const file = path.resolve(root, 'android/app/src/main/assets/public', name);
    assert(file.startsWith(path.resolve(root, 'android/app/src/main/assets/public') + path.sep));
    assert.equal(hash(await readFile(file)), expected, name);
  }
  const nativeFiles = await walk(path.join(root, 'android'));
  assert(!nativeFiles.some(file => /\.(?:jks|keystore|apk|aab)$/i.test(file)), 'no key or compiled artifact claimed');
  const packaged = await walk(path.join(root, 'android/app/src/main/assets'));
  for (const file of packaged) {
    assert(!/\.env(?:\.|$)/.test(path.basename(file)));
    assert.deepEqual(scanAssetText((await readFile(file)).toString('utf8')), [], path.relative(root, file));
  }
  const plugins = JSON.parse(await text('android/app/src/main/assets/capacitor.plugins.json'));
  for (const name of ['@capacitor/app', '@capacitor/browser', '@capacitor/preferences']) assert(plugins.some(p => p.pkg === name), name);
  const activity = await text('android/app/src/main/java/dev/knowledgeguide/sprite/MainActivity.java');
  const registration = activity.indexOf('registerPlugin(DurableDeviceStorePlugin.class)');
  const superCreate = activity.indexOf('super.onCreate(savedInstanceState);');
  assert(registration >= 0 && superCreate > registration, 'register local plugin before Bridge creation');
  const durable = await text('android/app/src/main/java/dev/knowledgeguide/sprite/DurableDeviceStorePlugin.java');
  assert(durable.includes('@CapacitorPlugin(name = "DurableDeviceStore")'));
  assert(durable.includes('getSharedPreferences(STORE, Context.MODE_PRIVATE)'));
  assert(durable.includes('"KnowledgeSpriteDevice"') && durable.includes('"knowledge-sprite.device."'));
  assert(durable.includes('10 * 1024 * 1024') && durable.includes('getBytes(StandardCharsets.UTF_8)'));
  assert(durable.includes('getBridge().execute(') && durable.includes('.commit()'));
  assert(durable.includes('if (!committed)') && durable.indexOf('if (!committed)') < durable.indexOf('result.put("committed", true)'));
  assert(!/\.apply\s*\(\s*\)\s*;|Executors\.|new Thread\(/.test(durable));
  assert.equal([...durable.matchAll(/@PluginMethod/g)].length, 2, 'only scoped get/set bridge surface');
  console.log(JSON.stringify({ status:'passed', kind:receipt.kind, releaseEligible:receipt.releaseEligible,
    sdk:{min:24,compile:36,target:36}, packagedFiles:packaged.length, pluginCount:plugins.length,
    localDurablePluginRegistrationSource:true, javaCompiled:false, nativeCommitExecuted:false,
    backupExcluded:true,cloudAndDeviceTransferExcluded:true,noSigningKeys:true,
    apkCompiled:false,installed:false,networkRequests:0 }));
} catch (error) {
  console.error(error instanceof Error ? error.message : 'mobile_check_failed');
  process.exitCode = 1;
}
