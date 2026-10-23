import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { CoursePage } from './deviceTypes';
import type { MobileApi } from './mobileApi';
import { CourseCover } from '../components/ResourceCard';
import { externalUrl } from '../safeUrls';
import { platformNames } from '../api';

export function SharedCourses({ api, onClose }: { api: MobileApi; onClose: () => void }) {
  const [query, setQuery] = useState(''), [platform, setPlatform] = useState(''), [page, setPage] = useState<CoursePage | null>(null);
  const [offset, setOffset] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null), heading = useRef<HTMLHeadingElement>(null);
  const load = async (nextOffset: number) => {
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    setBusy(true); setError('');
    try { const result = await api.courses(query, platform, nextOffset, next.signal);
      if (!next.signal.aborted) { setPage(result); setOffset(nextOffset); } }
    catch (reason) { if (!next.signal.aborted) setError((reason as Error).message); }
    finally { if (!next.signal.aborted) setBusy(false); }
  };
  useEffect(() => { heading.current?.focus(); void load(0); return () => controller.current?.abort(); }, []);
  const submit = (event: FormEvent) => { event.preventDefault(); void load(0); };
  return <section className="device-library" role="dialog" aria-modal="true" aria-labelledby="shared-course-title" onKeyDown={event => { if (event.key === 'Escape') onClose(); }}>
    <div className="device-library-heading"><h2 id="shared-course-title" ref={heading} tabIndex={-1}>共享课程库</h2><button className="text-button" onClick={onClose}>返回项目</button></div>
    <p>公开课程资料供所有设备查阅；不包含个人项目、勾选或学习进度。课程入库不代表完整匹配当前知识点。</p>
    <form onSubmit={submit} className="device-library-search"><label>课程关键词<input value={query} maxLength={120} onChange={event => setQuery(event.target.value)}/></label><label>平台<select value={platform} onChange={event => setPlatform(event.target.value)}><option value="">全部</option><option value="bilibili">B站</option><option value="icourse163">中国大学MOOC</option></select></label><button className="secondary-button" disabled={busy}>查找课程</button></form>
    {error && <p className="notice error-notice" role="alert">共享库暂时无法读取：{error}<button className="text-button" onClick={() => void load(offset)}>重新读取共享库</button></p>}
    {busy && <p role="status">正在读取公开课程资料…</p>}
    <div className="device-public-grid">{page?.items.filter(course => !!externalUrl(course.url)).map(course => <article className="device-public-course" key={course.course_id}>
      <CourseCover title={course.title} image={course.thumbnail_url} href={externalUrl(course.url)} action={course.resource_type === 'course' ? '查看课程' : '查看视频'}/>
      <h3>{course.title}</h3><p>{platformNames[course.platform] || course.platform}{course.author ? ` · ${course.author}` : ''}</p>
      {course.access_notice && <p>{course.access_notice}</p>}{Date.parse(course.expires_at) < Date.now() && <p>资料观察时间较早，最新情况请到平台核对。</p>}<p className="field-help">公开资料 · 具体教学内容与访问条件请到平台核对</p>
    </article>)}</div>
    {page && !page.items.length && !busy && <p role="status">共享库暂未找到相关课程，可换个专业词再试。</p>}
    {page && <div className="device-pagination"><button className="text-button" disabled={!offset || busy} onClick={() => void load(Math.max(0, offset - 12))}>上一页</button><span>公开资料 {page.total} 条</span><button className="text-button" disabled={!page.has_more || busy} onClick={() => void load(offset + 12)}>下一页</button></div>}
  </section>;
}
