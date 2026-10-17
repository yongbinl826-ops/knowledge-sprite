import { useState } from 'react';
import { externalUrl, platformNames } from '../api';
import type { ResourceItem, TopicEvidenceStatus } from '../types';
import { topicStatus } from '../topicEvidence';
import { recommendChapters } from '../chapterRecommendations';
import { BookIcon } from './Icons';

function CourseCover({ title, image, href }: { title: string; image?: string | null; href?: string }) {
  const [failedImage, setFailedImage] = useState<string>();
  const imageUrl = image ? externalUrl(image) : undefined;
  const content = <>
    {imageUrl && failedImage !== imageUrl
      ? <img src={imageUrl} alt={`${title}封面`} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailedImage(imageUrl)}/>
      : <div className="cover-placeholder"><BookIcon/><span>封面暂缺</span></div>}
    {href && <span className="cover-action"><span aria-hidden="true">↗</span> 去原平台学习</span>}
  </>;
  return href
    ? <a className="course-cover" href={href} target="_blank" rel="noopener noreferrer" aria-label={`前往原平台学习：${title}`}>{content}</a>
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
      <div className="learning-location">
        {chapters.length ? <><span className="location-label">{status === 'partial' ? '可参考章节' : '对应学习章节'}</span><ul>{chapters.map(chapter => <li key={chapter.evidenceId}>{chapter.chapterUrl ? <a className="chapter-link" href={chapter.chapterUrl} target="_blank" rel="noopener noreferrer">{chapter.title}</a> : chapter.title}</li>)}</ul></>
          : <p className="chapter-pending">{status === 'needs_review' ? '内容相关性待确认，可前往原平台查看。' : '具体章节待定位，可前往原平台查看。'}</p>}
      </div>
      {accessNote && <p className="course-access-note">{accessNote}</p>}
    </div>
  </article>;
}
