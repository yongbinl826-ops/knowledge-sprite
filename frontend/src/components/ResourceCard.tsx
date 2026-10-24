import { useState } from 'react';
import { courseImageUrl, externalUrl, platformNames } from '../api';
import type { ResourceItem, TopicEvidenceStatus } from '../types';
import { topicStatus } from '../topicEvidence';
import { recommendChapters } from '../chapterRecommendations';
import { BookIcon } from './Icons';

export function CourseCover({ title, image, href, action = '去原平台学习', coverOnly = false }: { title: string; image?: string | null; href?: string; action?: string; coverOnly?: boolean }) {
  const [failedImage, setFailedImage] = useState<string>();
  const [loadedImage, setLoadedImage] = useState<string>();
  const imageUrl = courseImageUrl(image);
  const imageLoaded = !!imageUrl && loadedImage === imageUrl && failedImage !== imageUrl;
  const content = <>
    {!imageLoaded && <div aria-hidden={coverOnly || undefined} className={`cover-placeholder cover-${/python|pygame|turtle/i.test(title) ? 'code' : /arduino|传感|硬件/i.test(title) ? 'hardware' : /pandas|excel|数据|图表/i.test(title) ? 'data' : 'learning'}`}>{!coverOnly && <span className="cover-letter" aria-hidden="true">{/python|pygame|turtle/i.test(title) ? 'Py' : /arduino|传感|硬件/i.test(title) ? 'IoT' : /pandas|excel|数据|图表/i.test(title) ? 'Data' : 'Learn'}</span>}<BookIcon/>{!coverOnly && <span>{image ? '封面暂不可用' : '来源未提供封面'}</span>}</div>}
    {/* A slow image keeps downloading above the placeholder until its real load
        or error event. A new URL gets its own element and can recover. */}
    {imageUrl && failedImage !== imageUrl && <img key={imageUrl} src={imageUrl} alt={coverOnly ? '' : `${title}封面`} loading="lazy" decoding="async" referrerPolicy="no-referrer" style={{ position: 'absolute', inset: 0, opacity: imageLoaded ? 1 : 0 }} onLoad={() => setLoadedImage(imageUrl)} onError={() => setFailedImage(imageUrl)}/>}
    {href && !coverOnly && <span className="cover-action"><span aria-hidden="true">↗</span> {action}</span>}
  </>;
  return href
    ? <a className="course-cover" href={href} target="_blank" rel="noopener noreferrer" aria-label={`${action === '去原平台学习' ? '前往原平台学习' : action}：${title}`}>{content}</a>
    : <div className="course-cover unavailable-cover">{content}</div>;
}

export function ResourceCard({ item, points, placement = 'supported' }: { item: ResourceItem; points: string[]; placement?: TopicEvidenceStatus }) {
  const { resource } = item;
  const href = externalUrl(resource.url);
  const status = topicStatus(item, placement);
  const chapters = status === 'needs_review' ? [] : recommendChapters(item, points, 2);
  const title = resource.title || '课程名称待确认';
  const accessNote = resource.access_notice || (resource.requires_payment ? '部分内容需要付费' : resource.requires_enrollment ? '学习前需要选课' : resource.requires_login ? '学习前需要登录' : '');
  return <article className="resource-card" data-resource-id={resource.resource_id} data-topic-status={status}>
    <CourseCover title={title} image={resource.thumbnail_url} href={href}/>
    <div className="course-info">
      <div className="course-meta"><span>{platformNames[resource.platform] || resource.platform}</span>{status !== 'supported' && <span className={`match-label match-${status}`}>{status === 'partial' ? '部分匹配' : '待核实'}</span>}</div>
      <h4>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{title}</a> : title}</h4>
      {item.match.recommendation_reason && <p className="recommendation-reason">{item.match.recommendation_reason}</p>}
      <div className="learning-location">
        {chapters.length ? <><span className="location-label">{status === 'partial' ? '可参考章节' : '对应学习章节'}</span><ul>{chapters.map(chapter => <li key={chapter.evidenceId}>{chapter.chapterUrl ? <a className="chapter-link" href={chapter.chapterUrl} target="_blank" rel="noopener noreferrer">{chapter.title}</a> : chapter.title}</li>)}</ul></>
          : <p className="chapter-pending">{status === 'needs_review' ? '内容相关性待确认，可前往原平台查看。' : '具体章节待定位，可前往原平台查看。'}</p>}
      </div>
      {accessNote && <p className="course-access-note">{accessNote}</p>}
      {href && <a className="course-outbound" href={href} target="_blank" rel="noopener noreferrer">去原平台学习 <span aria-hidden="true">↗</span><span className="sr-only">：{title}（在新窗口打开）</span></a>}
    </div>
  </article>;
}
