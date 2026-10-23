import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';

export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export async function walkFiles(dir) {
  const rows = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) throw new Error('mobile_symlink_not_allowed');
    if (/^\.env(?:\.|$)/i.test(entry.name)) throw new Error('mobile_env_file_not_allowed');
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) rows.push(...await walkFiles(absolute));
    else if (entry.isFile()) rows.push(absolute);
  }
  return rows.sort();
}
export async function fileHashes(dir, exclude = new Set()) {
  const rows = {};
  for (const absolute of await walkFiles(dir)) {
    const name = path.relative(dir, absolute).replaceAll('\\', '/');
    if (!exclude.has(name)) rows[name] = sha256(await readFile(absolute));
  }
  return rows;
}
export async function frontendSourceHashes(root) {
  const files = await walkFiles(path.join(root, 'src'));
  files.push(...['vite.config.ts', 'index.html', 'tsconfig.json'].map(name => path.join(root, name)));
  const result = {};
  for (const file of files.sort()) result[path.relative(root, file).replaceAll('\\', '/')] = sha256(await readFile(file));
  return result;
}
export function requireSameHashes(actual, expected, code) {
  const keys = Object.keys(actual).sort();
  if (JSON.stringify(keys) !== JSON.stringify(Object.keys(expected || {}).sort()) ||
      keys.some(key => actual[key] !== expected[key])) throw new Error(code);
}
