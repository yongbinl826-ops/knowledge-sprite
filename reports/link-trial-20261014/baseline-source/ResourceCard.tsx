import { dateLabel, externalUrl, platformNames } from '../api';
import type { Chapter, Evidence, FieldProvenance, ResourceItem } from '../types';
import { courseIdentityView, hasCoursePageEvidence } from '../identity';

const typeNames: Record<string, string> = { video: '视频', course: '课程', playlist: '系列视频', article: '文字教程', documentation: '文档', text: '文字资料', unknown: '类型未知' };
const fetchNames: Record<string, string> = { fetched: '已获取页面元信息', success: '已获取页面元信息', not_fetched: '页面详情尚未核验', search_only_policy: '仅保留搜索发现证据', robots_blocked: 'robots 规则或请求访问限制，已停止采集', robots_unavailable: '无法确认 robots 规则', captcha: '自动采集遇到验证码', login_required: '页面要求登录', not_found: '页面不存在', access_denied: '自动采集遇到访问限制', timeout: '页面请求超时', rate_limited: '来源限流', unsafe_url: '链接安全检查未通过', javascript_required: '页面需要 JavaScript', fetch_error: '页面采集失败', dns_error: '域名解析失败', network_error: '网络连接失败', error_page: '来源返回错误页面', disabled: '页面采集未启用', http_error: '页面 HTTP 请求失败', unsupported_content: '页面内容格式不受支持', too_large: '页面超过采集大小预算', budget_exceeded: '详情采集预算已用完', redirect_limit: '页面重定向次数超出限制' };
const basisNames: Record<string, string> = { title: '标题', snippet: '摘要', description: '页面描述', catalog: '目录证据' };
const authorRoleNames: Record<string, string> = { course_instructors: '课程教师', video_instructors: '本讲教师', credited_creator: '来源署名' };
const renderNames: Record<string, string> = { disabled: '未启用', rendered: '离线执行完成（不代表字段有增益）', render_timeout: '补全超时', cancelled: '已取消', render_incomplete: '依赖仍不完整', render_dependency_blocked: '存在未获准的依赖', render_host_not_enabled: '来源未在允许名单', render_failed: '补全失败', render_request_budget: '目标请求预算耗尽', render_dns_budget: 'DNS 请求预算耗尽', render_byte_budget: '字节预算耗尽', render_scope_blocked: '资源超出允许范围' };
const fieldNames: Record<string, string> = { title: '标题', description: '描述', resource_type: '课程类型', author: '作者', author_role: '作者角色', chapters: '目录', language: '语言', video_evidence_status: '视频结构' };
function countLabel(value: unknown) { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? String(value) : '未知'; }
Object.assign(fetchNames, { site_policy_blocked: '当前策略停止采集（查看来源依据）', policy_unreviewed: '采集许可尚未确认', budget_limited: '目录页采集预算不足', not_attempted: '目录页尚未尝试采集' });
function access(value: boolean | null | undefined) { return value == null ? '未知' : value ? '需要' : '无需'; }
function provenanceLabel(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value); }
function courseEntry(value: string): boolean {
  try {
    const url = new URL(value);
    const onHost = (host: string) => url.hostname === host || url.hostname.endsWith(`.${host}`);
    return (onHost('icourse163.org') && /^\/(?:course|learn)\/(?:[A-Za-z0-9_-]*-)?\d+\/?$/.test(url.pathname)) || (onHost('xuetangx.com') && /^\/course\/[A-Za-z0-9_-]+\/?$/.test(url.pathname));
  } catch { return false; }
}
function timestamp(seconds: number): string {
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}
function catalogUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value || value.length > 8192 || value.trim() !== value || /[\u0000-\u001f\u007f\\]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}
function validSeconds(value: unknown, duration = false): boolean {
  return value == null || (typeof value === 'number' && Number.isFinite(value) && (duration ? value > 0 : value >= 0));
}
function validChapterTimes(chapter: { start_seconds?: unknown; end_seconds?: unknown; duration_seconds?: unknown }): boolean {
  const { start_seconds: start, end_seconds: end, duration_seconds: duration } = chapter;
  return validSeconds(start) && validSeconds(end) && validSeconds(duration, true)
    && !(typeof start === 'number' && typeof end === 'number' && end < start);
}
type VerifiedChapter = { chapter: Chapter; record: Evidence; sourceUrl: string; href?: string; start?: number; duration?: number };
function catalogEntries(item: ResourceItem): VerifiedChapter[] {
  const records = new Map(item.evidence.filter(record => record.kind === 'catalog').map(record => [record.evidence_id, record]));
  return item.resource.chapters.flatMap((chapter, index) => {
    if (!chapter || typeof chapter.title !== 'string' || !chapter.title.trim()) return [];
    if (typeof chapter.evidence_id !== 'string' || !chapter.evidence_id.trim()) return [];
    const record = records.get(chapter.evidence_id);
    const sourceUrl = record ? catalogUrl(record.url) : undefined;
    if (!record || record.field !== `chapters.${index}` || !sourceUrl) return [];
    let fields: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(record.text || '');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return [];
      fields = parsed as Record<string, unknown>;
    } catch { return []; }
    // Missing and null both mean unknown; every claimed value must belong to this row.
    const keys = ['title', 'url', 'start_seconds', 'end_seconds', 'duration_seconds'] as const;
    if (keys.some(key => (fields[key] ?? null) !== (chapter[key] ?? null)) || !validChapterTimes(chapter) || !validChapterTimes(fields)) return [];
    const chapterHref = chapter.url == null ? undefined : catalogUrl(chapter.url);
    if (chapter.url != null && !chapterHref) return [];
    return [{ chapter, record, sourceUrl, href: chapterHref, start: chapter.start_seconds ?? undefined, duration: chapter.duration_seconds ?? undefined }];
  });
}

export function ResourceCard({ item, points }: { item: ResourceItem; points: string[] }) {
  const { resource: resource, match, evidence } = item;
  const identity = courseIdentityView(item);
  const href = externalUrl(resource.url);
  const verifiedPage = ['fetched', 'success'].includes(resource.fetch_status);
  const chapters = catalogEntries(item);
  const catalogStatus = resource.catalog_fetch_status;
  const catalogFailure = catalogStatus && !['fetched', 'success'].includes(catalogStatus) ? (fetchNames[catalogStatus] || `未知状态（${catalogStatus}）`) : null;
  const hasPageEvidence = ['page', 'catalog'].includes(resource.metadata_evidence_level);
  const evidenceName = chapters.length ? `目录证据（${chapters.length} 项）` : hasPageEvidence ? '页面元信息' : '搜索发现';
  const courseSearchCandidate = resource.resource_type === 'course' && href && courseEntry(href) && evidence.some(record => record.kind === 'search' && externalUrl(record.url) === href);
  const videoEvidenceName = resource.video_evidence_status === 'page_verified' ? '页面含视频结构证据' : resource.video_evidence_status === 'search_discovered' ? '搜索发现的视频候选' : hasCoursePageEvidence(item) ? '页面含课程结构证据 · 是否含视频未核验' : courseSearchCandidate ? '搜索发现的课程候选 · 是否含视频未核验' : '暂无视频结构证据';
  const render = resource.render_diagnostics;
  const domHash = render?.dom_sha256 && /^[a-f0-9]{64}$/i.test(render.dom_sha256) ? render.dom_sha256 : undefined;
  const renderSource = render?.source_url ? externalUrl(render.source_url) : undefined;
  const addedFields = render?.status === 'rendered' && domHash && render.render_id && Array.isArray(render.added_fields) ? render.added_fields.filter(field => {
    const provenance = resource.field_provenance[field] as FieldProvenance | undefined;
    return provenance?.acquisition === 'offline_rendered_dom' && provenance.dom_sha256 === domHash && provenance.render_id === render.render_id
      && evidence.some(record => record.evidence_id === provenance.evidence_id && ['page', 'catalog'].includes(record.kind)
        && record.field === field && record.acquisition === 'offline_rendered_dom' && record.dom_sha256 === domHash && record.render_id === render.render_id);
  }) : [];
  return <article className="resource-card">
    <div className="resource-meta"><span className="platform-label">{platformNames[resource.platform] || resource.platform}</span><span>{typeNames[resource.resource_type] || '类型未知'}</span><span className={`evidence-label ${resource.metadata_evidence_level === 'search' ? 'search-only' : ''}`}>{evidenceName}</span></div>
    <h4>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{resource.title || '标题未知'}<span className="external-arrow" aria-hidden="true">↗</span></a> : (resource.title || '标题未知')}</h4>
    <p className="matched-points">相关知识点：{points.join('、')}</p>
    <p className="identity-note">课程归属：{identity.family ? '已识别同来源课程' : '未知'} · 开课版本：{identity.offering ? '已识别' : '未知'} · 讲次：{identity.lesson ? '已识别' : '未知'}</p>
    <p className="recommendation">{match.recommendation_reason || '匹配依据尚未提供。'}</p>
    <p className="video-evidence-note">{videoEvidenceName}<span> · 页面元信息与目录不等于观看验证，观看尚未实测。</span></p>
    {!verifiedPage && <p className="verification-note">{resource.metadata_evidence_level === 'search' ? '仅搜索发现，页面详情未核验' : '已获取部分页面信息，内容详情尚未核验'}<span> · {fetchNames[resource.fetch_status] || `页面采集状态：${resource.fetch_status || '未知'}`}</span></p>}
    <p className={`catalog-note ${chapters.length ? 'has-catalog' : ''}`}>{chapters.length ? `已提取 ${chapters.length} 项目录证据，可展开查看章节及来源；不代表完整目录或已核验教学覆盖。` : '暂无可获取的目录证据，不代表来源没有目录。'}</p>
    {!chapters.length && catalogFailure && <p className="catalog-fetch-note">目录补全未完成：{catalogFailure}</p>}
    <div className="access-line"><span>登录：{access(resource.requires_login)}</span><span>付费：{access(resource.requires_payment)}</span><span>选课：{access(resource.requires_enrollment)}</span><span>浏览器访问：未逐页实测</span><span>可播放性：尚未核验</span></div>
    {resource.cache?.hit && <p className={`cache-note ${resource.cache.stale ? 'stale' : ''}`}>{resource.cache.stale ? '使用过期缓存' : '来自缓存'} · 缓存时间：{dateLabel(resource.cache.cached_at)}</p>}
    <div className="resource-bottom"><details className="evidence-details"><summary>查看来源与证据</summary><div className="evidence-content">
      <div className="identity-details"><h5>课程与讲次身份</h5><p>身份仅在同来源范围内识别，不自动合并跨站镜像。</p>{identity.familyUrl && <p><a href={identity.familyUrl} target="_blank" rel="noopener noreferrer">查看同来源课程入口</a></p>}{identity.sourceUrl && <p><a href={identity.sourceUrl} target="_blank" rel="noopener noreferrer">查看身份依据页面</a></p>}{identity.reason && <p>{identity.reason}</p>}</div>
      {render && <section className="render-diagnostics"><h5>受控 JS 补全</h5>
        <p>状态：{renderNames[render.status] || fetchNames[render.status] || `未知状态（${render.status}）`}</p>
        {render.page_status && <p>渲染后页面：{fetchNames[render.page_status] || render.page_status}</p>}
        <p>静态目录项：{countLabel(render.static_chapter_count)} · DOM 提取目录项：{countLabel(render.rendered_chapter_count)}。阶段计数不代替下方逐章证据。</p>
        <p>可对应来源的新增字段：{addedFields.length ? addedFields.map(field => fieldNames[field] || field).join('、') : '尚未确认'}</p>
        <p>来源 DOM SHA-256：<code>{domHash || '未知'}</code></p>
        {renderSource && <p><a href={renderSource} target="_blank" rel="noopener noreferrer">查看渲染来源页面</a></p>}
        <p>离线执行完成不等于教学覆盖或播放验证，观看仍未实测。</p>
      </section>}
      <dl><dt>{authorRoleNames[resource.author_role || ''] || '作者'}</dt><dd>{resource.author || '未知'}</dd><dt>语言</dt><dd>{resource.language || '未知'}</dd><dt>时长</dt><dd>{resource.duration_seconds == null ? '未知' : `${Math.floor(resource.duration_seconds / 60)} 分 ${resource.duration_seconds % 60} 秒`}</dd><dt>发布时间</dt><dd>{dateLabel(resource.published_at)}</dd><dt>发现时间</dt><dd>{dateLabel(resource.discovered_at)}</dd><dt>页面采集时间</dt><dd>{resource.fetched_at ? dateLabel(resource.fetched_at) : '尚未采集'}</dd><dt>内容匹配依据</dt><dd>{match.coverage_basis.map(basis => basisNames[basis] || basis).join('、') || '未知'}</dd><dt>内部排序分</dt><dd>{Number.isFinite(match.ranking_score) ? match.ranking_score.toFixed(2) : '未知'}（不是正确概率）</dd></dl>
      <h5>提取到的目录</h5>{chapters.length ? <ol className="chapter-list">{chapters.map(({ chapter, record, sourceUrl, href: chapterHref, start, duration }, index) => <li key={`${record.evidence_id}-${index}`}>
        <div className="chapter-title">{chapterHref ? <a href={chapterHref} target="_blank" rel="noopener noreferrer">{chapter.title}<span aria-hidden="true"> ↗</span></a> : <span>{chapter.title}</span>}{start != null && <span className="chapter-time">起始时间 {timestamp(start)}</span>}{duration != null && <span className="chapter-time">时长 {timestamp(duration)}</span>}</div>
        <div className="chapter-source">{!chapterHref && <span>章节直链未知 · </span>}<a href={sourceUrl} target="_blank" rel="noopener noreferrer">查看目录来源</a><span> · {record.source || '公开页面'} · {dateLabel(record.fetched_at || record.observed_at)}</span></div>
      </li>)}</ol> : <p className="catalog-empty">暂无可获取的目录证据，不代表来源没有目录。</p>}
      {resource.description && <p className="description">{resource.description}</p>}
      <h5>来源记录</h5>{evidence.length ? evidence.map(record => <div className="source-record" key={record.evidence_id}><strong>{record.kind === 'search' ? '搜索来源' : record.kind === 'catalog' ? '目录来源' : record.kind === 'site_policy' ? '条款核对' : record.kind === 'access_restriction' ? '访问限制记录' : '页面来源'} · {record.source}</strong>{record.query && <p>查询词：{record.query}</p>}{record.snippet && <p>{record.snippet}</p>}{['site_policy', 'access_restriction'].includes(record.kind) && record.text && <p>{record.text}</p>}<p>记录时间：{dateLabel(record.reviewed_at || record.fetched_at || record.observed_at)}</p>{record.cache?.hit && <p>{record.cache.stale ? '过期缓存' : '缓存'}：{dateLabel(record.cache.cached_at)}</p>}{externalUrl(record.url) && <a href={externalUrl(record.url)} target="_blank" rel="noopener noreferrer">{record.url}</a>}</div>) : <p>来源记录尚未返回。</p>}
      <h5>字段来源</h5>{Object.keys(resource.field_provenance).length ? <dl className="provenance">{Object.entries(resource.field_provenance).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{provenanceLabel(value)}</dd></div>)}</dl> : <p>字段来源未知。</p>}
    </div></details>{href ? <a className="visit-link" href={href} target="_blank" rel="noopener noreferrer">前往原平台 <span aria-hidden="true">↗</span></a> : <span className="muted">链接格式不可用</span>}</div>
  </article>;
}
