import { useEffect, useState, type CSSProperties } from 'react';
import { platformNames } from '../api';
import { externalUrl } from '../safeUrls';
import { hasProjectScopeMismatch, type ProjectPointResult, type ProjectVersion } from '../projectTypes';
import { groupItems, visibleGroupItems } from '../topicEvidence';
import { relatedTopicPointers, topicPointerEvidenceTexts } from '../topicPointers';
import type { Capabilities, Resource, SearchPipeline } from '../types';
import { CourseCover } from './ResourceCard';
import { visibleDiscoveredVideos } from './DiscoveredVideos';
import './ProjectVideoGallery.css';
import { nativeMotionAvailable, useMotionValue } from '../motion';
import { hasRelatedRecommendationPolicy, recommendationUrlKey, relatedRecommendations, verifiedReferenceChapterTarget } from '../relatedRecommendations';
import { isVerifiedVideoPage, type VideoPageFacts } from '../verifiedVideoPage';
import { hasEligibleReferenceLink, referenceLinkLabel } from '../relatedReferenceLink';
import { hasHelpfulVideoPolicy, helpfulVideoCovers, type HelpfulGalleryChapter } from '../helpfulVideoRecommendations';

type GalleryVideo = {
  id: string; title: string; image?: string | null; href: string;
  source: 'recommendation' | 'related-topic' | 'discovery' | 'related-reference' | 'helpful-video'; notice?: string; label?: string;
  knowledgePointIds: string[]; recommendedAt?: string;
  chapters?: HelpfulGalleryChapter[];
};
type CoverResource = Pick<Resource, 'resource_id' | 'title' | 'url' | 'canonical_url' | 'thumbnail_url' | 'platform'> & VideoPageFacts;

function GalleryCover({ video, index }: { video: GalleryVideo; index: number }) {
  // A native transition captures the destination as a still image. Capturing a
  // concurrently transparent CSS entrance would crossfade to an empty snapshot.
  // Keep this choice for this mounted card so later stream updates never replay it.
  const [nativeEntry] = useState(() => !!document.documentElement.dataset.motionKind);
  return <article className={`video-cover-card${nativeEntry ? ' motion-native-entry' : ''}`} data-resource-id={video.id} data-source-kind={video.source} data-knowledge-point-ids={video.knowledgePointIds.join(' ')} data-recommended-at={video.recommendedAt} title={video.notice} style={{ '--reveal-index': Math.min(index, 4) } as CSSProperties}>
    <CourseCover title={video.title} image={video.image} href={video.href} action={video.notice ? `${video.notice} 在原平台打开` : '在原平台打开'} coverOnly/>
    <h2 className="video-cover-title"><a href={video.href} target="_blank" rel="noopener noreferrer">{video.title}</a>{video.chapters?.map(chapter => <span key={chapter.chapter_id} data-chapter-id={chapter.chapter_id}>｜{chapter.href ? <a href={chapter.href} target="_blank" rel="noopener noreferrer">{chapter.title}</a> : chapter.title}</span>)}</h2>
    {video.label ? <span className="video-reference-label">{video.label}</span> : null}
  </article>;
}

export function ProjectVideoGallery({ version, points, capabilities, topic, pipeline, starting = false, onDisplayedChange }: {
  version: ProjectVersion; points: ProjectPointResult[]; capabilities: Capabilities | null; topic: string; pipeline?: SearchPipeline; starting?: boolean; onDisplayedChange?: (count: number) => void;
}) {
  const displayedTopic = useMotionValue(topic, 'topic');
  const [sourceFilter, setSourceFilter] = useState('all');
  const discoveryMode = capabilities?.teaching_match_enabled === false;
  const referencePolicy = points.some(point => point.result && !hasHelpfulVideoPolicy(point.result) && hasRelatedRecommendationPolicy(point.result));
  const byId = new Map(points.map(point => [point.project_knowledge_point_id, point]));
  const selected = (version.analysis?.knowledge_points || [])
    .filter(point => point.selection === 'learn' && (displayedTopic === 'all' || point.id === displayedTopic));
  const groups = selected.flatMap(planned => {
    const point = byId.get(planned.id);
    return point?.result && !hasProjectScopeMismatch(point) ? [{ planned, result: point.result }] : [];
  });
  const sourcePlatforms = [...new Set([
    'bilibili', 'icourse163', 'xuetangx',
    ...groups.flatMap(({ result }) => [
      ...groupItems(result).map(item => item.resource.platform),
      ...Object.keys(result.related_platform_recommendations || {}),
      ...(result.related_recommendations || []).map(entry => entry.resource.platform),
      ...(result.video_recommendations || []).map(entry => entry.resource.platform),
      ...Object.keys(result.discovery_platform_items || {}),
      ...(result.discovery_items || []).map(entry => entry.resource.platform),
      ...(result.related_topic_pointers || []).map(entry => entry?.resource?.platform),
    ]),
    sourceFilter,
  ])].filter((platform): platform is string => !!platform && platform !== 'all');
  const evidenceKey = discoveryMode && !referencePolicy ? JSON.stringify([...new Set(groups.flatMap(({ result }) => topicPointerEvidenceTexts(result)))]) : '[]';
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

  const covers = new Map<string, GalleryVideo>(helpfulVideoCovers(groups.map(({ planned, result }) => ({ pointId: planned.id, result })), sourceFilter));
  const addCover = (pointId: string, resource: CoverResource, source: GalleryVideo['source'], target = resource.url, notice?: string, label?: string) => {
    if (source !== 'related-reference' && !isVerifiedVideoPage(resource)) return;
    if (sourceFilter !== 'all' && resource.platform !== sourceFilter) return;
    const href = externalUrl(target);
    if (!href) return;
    const key = recommendationUrlKey(resource) || href;
    const previous = covers.get(key);
    const knowledgePointIds = [...new Set([...(previous?.knowledgePointIds || []), pointId])];
    if (!previous || source === 'recommendation' && previous.source !== 'recommendation') covers.set(key, {
      id: resource.resource_id, title: resource.title || '视频', image: resource.thumbnail_url, href, source, notice, label, knowledgePointIds,
    });
    else previous.knowledgePointIds = knowledgePointIds;
  };
  for (const { planned, result } of groups) {
    if (hasHelpfulVideoPolicy(result)) continue;
    const references = relatedRecommendations(result, sourceFilter);
    const rows = visibleGroupItems(result, sourceFilter, 'learning', result.section_limit || capabilities?.limits.max_results_per_point || 5);
    for (const { item, status } of rows) {
      if (discoveryMode && !referencePolicy || status === 'supported' || status === 'partial') {
        const chapter = references.map(entry => verifiedReferenceChapterTarget(item.resource, entry, result.knowledge_point_id)).find(Boolean);
        addCover(planned.id, item.resource, 'recommendation', chapter || item.resource.url);
      }
    }
    for (const entry of references) {
      if (hasEligibleReferenceLink(entry)) {
        const label = referenceLinkLabel(entry);
        const notice = entry.reference.link_eligible === true
          ? `${label || '相关参考'}；精确讲授未验证。${entry.reference.basis.every(kind => !['page', 'catalog'].includes(kind)) ? '页面未核验。' : ''}`
          : entry.accessibleReason;
        addCover(planned.id, entry.resource, 'related-reference', entry.href, notice, label);
      }
    }
    // Keep the existing proof checks before showing a related chapter's cover.
    if (discoveryMode && !referencePolicy) {
      for (const entry of relatedTopicPointers(planned, result, sourceFilter, digests.key === evidenceKey ? digests.values : new Map())) {
        addCover(planned.id, entry.resource, 'related-topic', entry.targetUrl);
      }
      for (const entry of visibleDiscoveredVideos(result, sourceFilter)) addCover(planned.id, entry.resource, 'discovery');
    }
  }
  const displayedCount = covers.size;
  useEffect(() => { onDisplayedChange?.(displayedCount); }, [displayedCount, onDisplayedChange]);
  const checking = evidenceKey !== '[]' && digests.key !== evidenceKey;
  const terminal = new Set(['completed', 'partial', 'no_results', 'failed', 'cancelled', 'interrupted', 'budget_exceeded', 'scope_mismatch', 'not_selected', 'skip', 'mastered']);
  const searching = starting || version.status === 'running' && selected.some(planned => {
    const point = byId.get(planned.id);
    return !hasProjectScopeMismatch(point) && !terminal.has(point?.status || 'not_started');
  });

  return <section className="project-video-gallery" aria-label="视频封面" aria-description={referencePolicy ? '包含相关参考；精确讲授未验证，请到原平台核对。' : undefined} aria-busy={pipeline ? undefined : searching || checking}>
    <div className="gallery-toolbar">
      <label><span>来源</span><select aria-label="视频来源" value={sourceFilter} onChange={event => setSourceFilter(event.target.value)}>
        <option value="all">全部</option>
        {sourcePlatforms.map(platform => <option key={platform} value={platform}>{platform === 'icourse163' ? 'MOOC' : platformNames[platform] || capabilities?.platforms.find(entry => entry.id === platform)?.name || platform}</option>)}
      </select></label>
    </div>
    <div className={`gallery-motion${nativeMotionAvailable() ? '' : ' motion-fallback'}`} key={`${displayedTopic}:${sourceFilter}`}>
    {covers.size ? <div className="course-grid">{[...covers].map(([key, video], index) => <GalleryCover key={key} video={video} index={index}/>)}
    </div> : searching || checking ? <div className="course-grid" role="status" aria-label={starting ? '正在开始视频检索' : '正在读取视频封面'}>
      {[1, 2, 3].map(index => <div className="video-cover-skeleton" key={index} aria-hidden="true"/>)}
    </div> : <div className="video-gallery-empty" role="status" aria-label={sourceFilter === 'all' ? '这个知识点暂未找到视频' : '该来源暂无视频，可切换其他来源。'} data-filtered={sourceFilter !== 'all'}>
      <svg width="56" height="42" viewBox="0 0 56 42" fill="none" aria-hidden="true"><rect x="1" y="1" width="54" height="40" rx="6" stroke="currentColor" strokeWidth="1.5"/><path d="m23 13 12 8-12 8V13Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>
      {sourceFilter !== 'all' && <span>该来源暂无视频，可切换其他来源。</span>}
    </div>}</div>
  </section>;
}
