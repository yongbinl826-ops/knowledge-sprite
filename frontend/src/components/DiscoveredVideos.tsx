import { externalUrl, platformNames } from '../api';
import type { DiscoveredVideo, ResultGroup } from '../types';
import { CourseCover } from './ResourceCard';

export function visibleDiscoveredVideos(result: ResultGroup | null | undefined, platform: string): DiscoveredVideo[] {
  const rows = platform === 'all' ? result?.discovery_items : result?.discovery_platform_items?.[platform] ?? result?.discovery_items?.filter(row => row.resource.platform === platform);
  return [...new Map((rows || []).filter(row => externalUrl(row.resource.url)).map(row => [row.resource.resource_id, row])).values()];
}

export function DiscoveredVideos({ rows }: { rows: DiscoveredVideo[] }) {
  if (!rows.length) return null;
  return <section className="discovered-videos" aria-label="检索到的课程与视频">
    <p>以下是本知识点检索到的全部课程与视频，可直接到原平台查看。</p>
    <div className="course-grid">{rows.map(({ resource }) => {
      const href = externalUrl(resource.url)!;
      const read = ['fetched', 'success'].includes(resource.fetch_status);
      const kind = resource.resource_type === 'course' ? '课程' : '视频';
      return <article className="resource-card discovery-card" key={resource.resource_id} data-resource-id={resource.resource_id}>
        <CourseCover title={resource.title} image={resource.thumbnail_url} href={href} action={`查看${kind}`}/>
        <div className="course-info"><div className="course-meta"><span>{platformNames[resource.platform] || resource.platform}</span><span className="match-label match-needs_review">{read ? '页面已读取' : '搜索发现'}</span></div>
          <h4><a href={href} target="_blank" rel="noopener noreferrer">{resource.title}</a></h4>
          <a className="course-outbound" href={href} target="_blank" rel="noopener noreferrer">到平台查看{kind} <span aria-hidden="true">↗</span></a>
        </div>
      </article>;
    })}</div>
  </section>;
}
