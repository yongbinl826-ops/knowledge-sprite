import { useEffect, useState } from 'react';
import { externalUrl } from '../safeUrls';
import { hasProjectScopeMismatch, type ProjectPointResult, type ProjectVersion } from '../projectTypes';
import { visibleGroupItems } from '../topicEvidence';
import { relatedTopicPointers, topicPointerEvidenceTexts } from '../topicPointers';
import type { Capabilities, Resource, SearchPipeline } from '../types';
import { CourseCover } from './ResourceCard';
import { SearchPipelineProgress } from './SearchPipelineProgress';
import './ProjectVideoGallery.css';

type GalleryVideo = {
  id: string; title: string; image?: string | null; href: string;
  source: 'recommendation' | 'related-topic' | 'discovery';
};
type CoverResource = Pick<Resource, 'resource_id' | 'title' | 'url' | 'canonical_url' | 'thumbnail_url'>;

export function ProjectVideoGallery({ version, points, capabilities, topic, pipeline }: {
  version: ProjectVersion; points: ProjectPointResult[]; capabilities: Capabilities | null; topic: string; pipeline?: SearchPipeline;
}) {
  const byId = new Map(points.map(point => [point.project_knowledge_point_id, point]));
  const selected = (version.analysis?.knowledge_points || [])
    .filter(point => point.selection === 'learn' && (topic === 'all' || point.id === topic))
    .sort((a, b) => a.learning_order - b.learning_order);
  const groups = selected.flatMap(planned => {
    const point = byId.get(planned.id);
    return point?.result && !hasProjectScopeMismatch(point) ? [{ planned, result: point.result }] : [];
  });
  const evidenceKey = JSON.stringify([...new Set(groups.flatMap(({ result }) => topicPointerEvidenceTexts(result)))]);
  const [digests, setDigests] = useState(() => ({ key: '', values: new Map<string, string>() }));
  useEffect(() => {
    let stale = false;
    void Promise.all((JSON.parse(evidenceKey) as string[]).map(async text => {
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [text, [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')] as const;
    })).then(values => { if (!stale) setDigests({ key: evidenceKey, values: new Map(values) }); })
      .catch(() => { if (!stale) setDigests({ key: evidenceKey, values: new Map() }); });
    return () => { stale = true; };
  }, [evidenceKey]);

  const covers = new Map<string, GalleryVideo>();
  const addCover = (resource: CoverResource, source: GalleryVideo['source'], target = resource.url) => {
    const href = externalUrl(target);
    if (!href) return;
    const key = externalUrl(resource.canonical_url) || href;
    if (!covers.has(key)) covers.set(key, {
      id: resource.resource_id, title: resource.title || '视频', image: resource.thumbnail_url, href, source,
    });
  };
  for (const { planned, result } of groups) {
    const rows = visibleGroupItems(result, 'all', 'learning', result.section_limit || capabilities?.limits.max_results_per_point || 5);
    for (const { item } of rows) addCover(item.resource, 'recommendation');
    // Keep the existing proof checks before showing a related chapter's cover.
    for (const entry of relatedTopicPointers(planned, result, 'all', digests.key === evidenceKey ? digests.values : new Map())) {
      addCover(entry.resource, 'related-topic', entry.targetUrl);
    }
    for (const entry of result.discovery_items || []) addCover(entry.resource, 'discovery');
  }
  const checking = evidenceKey !== '[]' && digests.key !== evidenceKey;
  const terminal = new Set(['completed', 'partial', 'no_results', 'failed', 'cancelled', 'interrupted', 'budget_exceeded', 'scope_mismatch', 'not_selected', 'skip', 'mastered']);
  const searching = version.status === 'running' && selected.some(planned => {
    const point = byId.get(planned.id);
    return !hasProjectScopeMismatch(point) && !terminal.has(point?.status || 'not_started');
  });

  return <section className="project-video-gallery" aria-label="视频封面" aria-busy={pipeline ? undefined : searching || checking}>
    {pipeline && <SearchPipelineProgress pipeline={pipeline} displayed={covers.size}/>}
    {covers.size ? <div className="course-grid">{[...covers].map(([key, video]) =>
      <article className="video-cover-card" key={key} data-resource-id={video.id} data-source-kind={video.source}>
        <CourseCover title={video.title} image={video.image} href={video.href} action="在原平台打开" coverOnly/>
      </article>)}
    </div> : searching || checking ? <div className="course-grid" role="status" aria-label="正在读取视频封面">
      {[1, 2, 3].map(index => <div className="video-cover-skeleton" key={index} aria-hidden="true"/>)}
    </div> : <div className="video-gallery-empty" role="status" aria-label="这个知识点暂未找到视频">
      <svg width="56" height="42" viewBox="0 0 56 42" fill="none" aria-hidden="true"><rect x="1" y="1" width="54" height="40" rx="6" stroke="currentColor" strokeWidth="1.5"/><path d="m23 13 12 8-12 8V13Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>
    </div>}
  </section>;
}
