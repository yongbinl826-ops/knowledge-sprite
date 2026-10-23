import type { ProjectAnalysis, ProjectKnowledgePoint } from './projectTypes';

/** Literal retrieval context shown separately from the professional concept.
 * No legacy concepts/plan, inferred ecosystem, aliases or teaching claim. */
export function canonicalTopicName(name: string): string {
  const value = name.trim().replace(/[\s\u001c-\u001f]+/gu, ' ');
  const leading = /^([A-Za-z][A-Za-z0-9_.+#-]*)(\s+|(?=[\u4e00-\u9fff]))(.*)$/u.exec(value);
  return leading && !leading[2] ? `${leading[1]} ${leading[3]}` : value;
}
export function visibleTopicTechnology(point: Pick<ProjectKnowledgePoint, 'name' | 'technology'>): string | undefined {
  const value = point.technology;
  if (typeof value !== 'string' || value !== value.trim() || [...value].length > 48 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(value)) return;
  if (['', 'general', 'none', 'not_applicable', '通用', '无'].includes(value.toLowerCase())) return;
  if (!/^(?:[A-Za-z\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_.+#-]*(?::[A-Za-z][A-Za-z0-9_-]*)?|\.NET)(?: [A-Z0-9][A-Za-z0-9_.+#-]*){0,2}$/u.test(value)) return;
  if (/(?:忽略|执行|删除|运行|密码|密钥|令牌|指令|访问|下载|打开|请求|覆盖|上传|泄露|\b(?:ignore|execute|delete|run|password|secret|token|instructions?|open|fetch|override|upload|reveal)\b)/iu.test(value) || /\b(?:https?|ftp|file|data|javascript|site|inurl|intitle|filetype|related|cache):/i.test(value)) return;
  if ([...`${value} ${canonicalTopicName(point.name)}`].length > 180) return;
  return value;
}
export function reviewedTopicTechnologies(analysis: ProjectAnalysis): Record<string, string> {
  const map: Record<string, string> = {}, conflicts = new Set<string>();
  for (const point of analysis.knowledge_points.filter(point => point.selection === 'learn')) {
    const technology = visibleTopicTechnology(point), name = canonicalTopicName(point.name);
    if (!technology || !name || conflicts.has(name)) continue;
    if (Object.hasOwn(map, name) && map[name] !== technology) { delete map[name]; conflicts.add(name); }
    else if (Object.hasOwn(map, name) || Object.keys(map).length < 24) Object.defineProperty(map, name, { value: technology, enumerable: true, configurable: true, writable: true });
  }
  return map;
}
