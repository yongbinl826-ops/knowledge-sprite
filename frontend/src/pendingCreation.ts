import type { SearchRequest } from './types';

const storageKey = 'knowledge-guide.pending-creation.v1';
export type PendingCreation = { body: string; key: string };

export function readPendingCreation(): PendingCreation | null {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return null;
    if (raw.length > 10000) throw new Error('invalid saved request');
    const value = JSON.parse(raw);
    if (typeof value?.key !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.key) || typeof value.body !== 'string') throw new Error('invalid saved request');
    const request = JSON.parse(value.body);
    const fields = ['knowledge_points', 'student_level', 'language', 'technical_version', 'project_context', 'preferred_platforms'];
    if (!request || Object.keys(request).length !== fields.length || !fields.every(field => field in request)
      || !Array.isArray(request.knowledge_points) || !request.knowledge_points.length || request.knowledge_points.length > 5
      || !request.knowledge_points.every((point: unknown) => typeof point === 'string' && point.trim() && point.length <= 160)
      || !['beginner', 'intermediate', 'advanced', 'any'].includes(request.student_level) || !['zh', 'en', 'any'].includes(request.language)
      || typeof request.technical_version !== 'string' || request.technical_version.length > 100
      || typeof request.project_context !== 'string' || request.project_context.length > 1000
      || !Array.isArray(request.preferred_platforms) || !request.preferred_platforms.every((platform: unknown) => ['bilibili', 'icourse163', 'xuetangx'].includes(String(platform)))) throw new Error('invalid saved request');
    return { body: value.body, key: value.key };
  } catch {
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage can be disabled by the browser. */ }
    return null;
  }
}

export function savePendingCreation(value: PendingCreation | null): boolean {
  try {
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
    else sessionStorage.removeItem(storageKey);
    return true;
  } catch { return false; }
}

export function pendingRequest(value: PendingCreation | null): SearchRequest | null {
  return value ? JSON.parse(value.body) as SearchRequest : null;
}
