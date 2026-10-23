import { platformNames } from '../api';
import type { VisibleReference } from '../relatedRecommendations';
import { CourseCover } from './ResourceCard';

export function RelatedRecommendations({ rows }: { rows: VisibleReference[] }) {
  if (!rows.length) return null;
  return <section className="related-recommendations" aria-label="相关参考">
    <p className="section-caption">相关参考 · 精确讲授未验证，请到原平台核对内容。</p>
    <div className="course-grid">{rows.map(({ resource, reference, href, urlKey, accessibleReason }) => {
      const kind = resource.resource_type === 'course' ? '课程' : ['video', 'playlist'].includes(resource.resource_type) ? '视频' : '资源';
      return <article className="resource-card" key={urlKey} data-resource-id={resource.resource_id} data-source-kind="related-reference">
        <CourseCover title={resource.title} image={resource.thumbnail_url} href={href} action={`查看${kind}`}/>
        <div className="course-info">
          <div className="course-meta"><span>{platformNames[resource.platform] || resource.platform}</span><span className="match-label match-needs_review">相关参考</span></div>
          <h4><a href={href} target="_blank" rel="noopener noreferrer">{resource.title}</a></h4>
          <p className="recommendation-reason">{reference.reason}</p>
          {resource.access_notice && <p className="course-access-note">{resource.access_notice}</p>}
          <a className="course-outbound" href={href} target="_blank" rel="noopener noreferrer" aria-label={`${resource.title}；${accessibleReason}；在新窗口查看${kind}`}>到平台查看{kind} <span aria-hidden="true">↗</span></a>
        </div>
      </article>;
    })}</div>
  </section>;
}
