import { externalUrl } from './api';
import type { ResourceItem } from './types';

const tracking = new Set(['fbclid', 'gclid', 'dclid', 'msclkid', 'igshid', 'spm_id_from', 'vd_source', 'from_spmid', 'spmid', 'share_source', 'share_medium', 'share_plat', 'share_session_id', 'share_tag', 'mc_cid', 'mc_eid']);
export function observedUrl(value: string): string | undefined {
  const safe = externalUrl(value);
  if (!safe) return undefined;
  const url = new URL(safe);
  url.hostname = url.hostname.replace(/\.$/, '');
  const biliVideo = (url.hostname === 'bilibili.com' || url.hostname.endsWith('.bilibili.com')) && /^\/video\/(?:BV[0-9A-Za-z]{10}|av\d+)\/?$/.test(url.pathname);
  for (const key of [...url.searchParams.keys()]) {
    if (key.toLowerCase().startsWith('utm_') || tracking.has(key.toLowerCase()) || (biliVideo && key.toLowerCase() === 'uid')) url.searchParams.delete(key);
  }
  return url.href;
}

export function hasCoursePageEvidence({ resource, evidence }: Pick<ResourceItem, 'resource' | 'evidence'>): boolean {
  const provenance = resource.field_provenance.resource_type as { evidence_id?: string; source?: string; url?: string } | undefined;
  if (resource.resource_type !== 'course' || !['fetched', 'success'].includes(resource.fetch_status) || !['page', 'catalog'].includes(resource.metadata_evidence_level) || !provenance || !['jsonld.@type', 'html.mit_ocw.course_home', 'html.microsoft_ai.curriculum_table', 'html.icourse163.course_structure', 'html.icourse163.embedded_course_structure'].includes(provenance.source || '')) return false;
  return evidence.some(record => {
    const recordUrl = observedUrl(record.url);
    return record.evidence_id === provenance.evidence_id && record.kind === 'page' && record.field === 'resource_type'
      && record.source === provenance.source && !!record.text && !!recordUrl
      && [observedUrl(resource.url), resource.resolved_url ? observedUrl(resource.resolved_url) : undefined].includes(recordUrl)
      && (!provenance.url || observedUrl(provenance.url) === recordUrl)
      && (provenance.source !== 'jsonld.@type' || record.text.trim().toLowerCase() === 'course');
  });
}

export function courseIdentityView({ resource, evidence }: ResourceItem) {
  const identity = resource.course_identity;
  const sourceUrl = identity?.source_url ? observedUrl(identity.source_url) : undefined;
  const ids = new Set(identity?.evidence_ids || []);
  const records = evidence.filter(record => ids.has(record.evidence_id));
  let backed = false;
  if (identity && sourceUrl && ['identified', 'partial'].includes(identity.status)) {
    if (identity.basis === 'recognized_url') {
      backed = records.some(record => ['search', 'page', 'page_link'].includes(record.kind) && observedUrl(record.url) === sourceUrl);
    } else if (identity.basis === 'page_course') {
      backed = hasCoursePageEvidence({ resource, evidence }) && records.some(record => record.kind === 'page' && record.field === 'resource_type' && observedUrl(record.url) === sourceUrl);
    } else if (identity.basis === 'page_is_part_of') {
      const provenance = resource.field_provenance.parent_course_url as { evidence_id?: string } | undefined;
      const parentUrl = resource.parent_course_url ? observedUrl(resource.parent_course_url) : undefined;
      backed = !!parentUrl && records.some(record => {
        if (record.evidence_id !== provenance?.evidence_id || record.kind !== 'page' || record.field !== 'parent_course_url' || !['jsonld.isPartOf.Course', 'html.explicit_course_parent'].includes(record.source)) return false;
        try {
          const fields = JSON.parse(record.text || '');
          return fields?.['@type'] === 'Course' && observedUrl(fields.url) === parentUrl
            && new URL(parentUrl).origin === new URL(sourceUrl).origin && observedUrl(record.url) === sourceUrl;
        } catch { return false; }
      });
    }
  }
  return { family: backed && !!identity?.family_id, offering: backed && !!identity?.offering_id,
    lesson: backed && !!identity?.lesson_id, sourceUrl: backed ? sourceUrl : undefined,
    familyUrl: backed && identity?.family_id && identity.family_url ? externalUrl(identity.family_url) : undefined,
    reason: identity?.unknown_reason || (!backed ? '尚无可对应的课程身份依据。' : null) };
}
