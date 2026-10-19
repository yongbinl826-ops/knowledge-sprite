import type { CollectionCoverage, ResourceItem } from './types';

export type ValidatedCoverageRow = {
  part: CollectionCoverage['subtopics'][number];
  sources: { item: ResourceItem; ids: string[] }[];
};
export type DisplayCoverageRow = {
  key: string;
  text: string;
  memberIds: string[];
  members: ValidatedCoverageRow[];
  status: 'supported' | 'unknown';
  sources: ValidatedCoverageRow['sources'];
};

// Presentation only: rows have already passed version, visibility, ID/text and
// own-source checks. A repeated title/confirmed target never lends support to
// an unknown member. Keep every original requirement and evidence reference.
export function groupCoverageRows(rows: ValidatedCoverageRow[]): DisplayCoverageRow[] {
  const byText = new Map<string, ValidatedCoverageRow[]>();
  for (const row of rows) {
    const group = byText.get(row.part.text) || [];
    group.push(row);
    byText.set(row.part.text, group);
  }
  const emitted = new Set<string>();
  const groups: DisplayCoverageRow[] = [];
  const isTarget = (row: ValidatedCoverageRow) => /^learning_target_[1-8]$/.test(row.part.id);
  for (const row of rows) {
    const exact = byText.get(row.part.text)!;
    const merge = exact.some(isTarget) && exact.some(item => !isTarget(item));
    if (merge && emitted.has(row.part.text)) continue;
    const members = merge ? exact : [row];
    if (merge) emitted.add(row.part.text);
    const supported = members.every(item => item.sources.length > 0 && (!merge || item.part.status === 'supported'));
    const sources = new Map<string, ValidatedCoverageRow['sources'][number]>();
    if (supported) for (const member of members) for (const source of member.sources) {
      const key = source.item.resource.resource_id;
      const prior = sources.get(key);
      sources.set(key, { item: source.item, ids: [...new Set([...(prior?.ids || []), ...source.ids])] });
    }
    groups.push({
      key: members.map(member => `${member.part.id.length}:${member.part.id}`).join('|'),
      text: row.part.text,
      memberIds: members.map(member => member.part.id),
      members,
      status: supported ? 'supported' : 'unknown',
      sources: [...sources.values()],
    });
  }
  return groups;
}
