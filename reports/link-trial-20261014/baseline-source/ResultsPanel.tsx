import { useState } from 'react';
import { dateLabel, platformNames, statusNames } from '../api';
import type { Capabilities, SearchJob, SearchResults } from '../types';
import { ResourceCard } from './ResourceCard';
import { SearchIcon } from './Icons';

const phaseNames: Record<string, string> = { queued: '等待执行', expanding: '生成查询词', searching: '搜索课程与视频', fetching: '补全公开元信息', ranking: '匹配与排序', done: '已结束' };
const isRunning = (job: SearchJob) => ['queued', 'running'].includes(job.status);
type Props = { capabilities: Capabilities | null; capabilityError: string; job: SearchJob | null; results: SearchResults | null; jobId: string; error: string; notice: string; canCancel: boolean; cancelling: boolean; onCancel: () => void; onRetry: () => void; onRefresh: () => void };
export function ResultsPanel({ capabilities, capabilityError, job, results, jobId, error, notice, canCancel, cancelling, onCancel, onRetry, onRefresh }: Props) {
  const [filter, setFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const platforms = [...new Set(results?.groups.flatMap(group => group.platform_items ? Object.keys(group.platform_items) : group.items.map(item => item.resource.platform)) || [])];
  const activeFilter = platforms.includes(filter) ? filter : 'all';
  const pointMap = new Map<string, string[]>();
  for (const group of results?.groups || []) for (const item of [...group.items, ...Object.values(group.platform_items || {}).flat()]) {
    pointMap.set(item.resource.resource_id, [...new Set([...(pointMap.get(item.resource.resource_id) || []), group.text])]);
  }
  const warnings = [...new Set([...(job?.warnings || []), ...(results?.warnings || [])])];
  const unconfigured = capabilities?.search.status === 'unconfigured';
  const fault = capabilities?.search.status === 'fault';
  return <section className="results-panel panel" aria-labelledby="results-title">
    <div className="section-heading"><div><h2 id="results-title">学习资源</h2><p>按知识点整理 · 保留来源证据</p></div>{job && <span className={`job-status status-${job.status}`}>{statusNames[job.status]}</span>}</div>
    {capabilityError && <div className="notice error-notice" role="alert"><strong>暂时无法连接后端</strong><p>{capabilityError}</p><button className="text-button" onClick={onRefresh}>重新检查连接</button></div>}
    {(unconfigured || fault) && <div className="notice warning-notice"><span className="notice-icon" aria-hidden="true">!</span><div><strong>{unconfigured ? '搜索服务尚未配置' : '搜索服务暂时不可用'}</strong><p>{capabilities?.search.message || '请先在服务端接入 SearXNG，或启用已配置的 Tavily。'}</p></div></div>}
    {error && <div className="notice error-notice" role="alert"><strong>请求未完成</strong><p>{error}</p>{jobId && <button className="text-button" onClick={onRetry}>重新读取任务</button>}</div>}
    {notice && <p className="action-notice" role="status">{notice}</p>}
    {canCancel && <div className="task-actions"><button className="secondary-button" disabled={cancelling} onClick={onCancel}>{cancelling ? '正在取消…' : '取消任务'}</button><span>取消后保留已获取的结果与证据。</span></div>}
    {job && <div className="task-progress" aria-live="polite"><div className="progress-title"><strong>{phaseNames[job.phase] || job.phase}</strong><span>更新于 {dateLabel(job.updated_at)}</span></div><div className="progress-counts"><span>查询 <b>{job.progress.queries_completed} / {job.progress.queries_planned}</b></span><span>发现候选 <b>{job.progress.candidates_discovered}</b></span><span>详情采集 <b>{job.progress.details_completed} / {job.progress.details_attempted}</b></span>{job.progress.catalog_pages_attempted != null && <span>目录页采集 <b>{job.progress.catalog_pages_completed ?? 0} / {job.progress.catalog_pages_attempted}</b></span>}{job.progress.details_cached != null && <span>详情缓存 <b>{job.progress.details_cached}</b></span>}<span>缓存命中 <b>{job.progress.cache_hits}</b></span></div><p>实际搜索请求：{job.progress.search_requests} / {job.budgets.max_search_requests} 次；详情与目录页共用 {job.budgets.max_detail_pages} 页预算，采集计数分别列示。</p></div>}
    {job?.status === 'partial' && <div className="notice warning-notice"><strong>部分搜索或信息补全未完成</strong><p>已保留当前可用结果；请结合下方失败记录判断搜索范围。</p></div>}
    {job?.status === 'completed' && <p className="completion-boundary">本次任务流程已结束；不代表每个平台均有结果，或每个页面、目录与播放条件都已核验。</p>}
    {job?.status === 'cancelled' && <div className="notice warning-notice"><strong>已按你的操作取消</strong><p>已获取的结果与来源证据仍可查看；未完成部分保持未知。再次开始查找会创建新任务。</p></div>}
    {job?.status === 'interrupted' && <div className="notice warning-notice"><strong>任务已中断</strong><p>服务重启中断了该任务。已保存的结果仍可查看，请重新提交学习需求以再次执行。</p></div>}
    {job?.status === 'failed' && <div className="notice error-notice" role="alert"><strong>本次检索未能完成</strong><p>请检查搜索服务配置或网络连接后重新提交。</p></div>}
    {(warnings.length > 0 || !!job?.errors.length) && <details className="task-records"><summary>搜索范围与异常记录（{warnings.length + (job?.errors.length || 0)}）</summary><ul>{warnings.map((warning, index) => <li key={`w${index}`}>{warning}</li>)}{job?.errors.map((record, index) => <li key={`e${index}`}>{record.message} <code>{record.code}</code></li>)}</ul></details>}
    {results && <>
      {results.identity_summary?.scope === 'observed_source_scoped_identities_not_global_course_deduplication' && <p className="identity-summary">已返回 {results.identity_summary.resource_records} 条资源；识别到 {results.identity_summary.identified_course_families} 个同来源课程身份、{results.identity_summary.identified_course_offerings} 个开课版本、{results.identity_summary.identified_lessons} 个讲次身份。{results.identity_summary.unknown_course_family_resources} 条资源的课程归属未知。统计仅针对已返回资源，不是跨网站独立课程总数。</p>}
      <div className="results-toolbar"><div className="result-filter"><label htmlFor="platform-filter">来源平台</label><select id="platform-filter" value={activeFilter} onChange={e => setFilter(e.target.value)}><option value="all">全部平台</option>{platforms.map(platform => <option key={platform} value={platform}>{platformNames[platform] || platform}</option>)}</select></div><div className="result-filter"><label htmlFor="resource-type-filter">资源类型</label><select id="resource-type-filter" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}><option value="all">全部类型</option><option value="learning">课程与视频</option><option value="text">文字资料</option><option value="unknown">类型未知</option></select></div><span>每个知识点最多 {capabilities?.limits.max_results_per_point || 5} 项</span></div>
      <div className="result-groups">{results.groups.map(group => {
        const platformItems = activeFilter === 'all' ? group.items : group.platform_items?.[activeFilter] ?? group.items.filter(item => item.resource.platform === activeFilter);
        const visibleItems = platformItems.filter(item => {
          if (activeFilter !== 'all' && item.resource.platform !== activeFilter) return false;
          const type = item.resource.resource_type;
          if (typeFilter === 'learning') return ['video', 'course', 'playlist'].includes(type);
          if (typeFilter === 'text') return ['article', 'documentation', 'text'].includes(type);
          if (typeFilter === 'unknown') return !['video', 'course', 'playlist', 'article', 'documentation', 'text'].includes(type);
          return true;
        });
        return <section className="result-group" key={group.knowledge_point_id} aria-labelledby={`group-${group.knowledge_point_id}`}><div className="group-heading"><h3 id={`group-${group.knowledge_point_id}`}>{group.text}</h3><span>{visibleItems.length} 个候选</span></div>
          {!visibleItems.length ? <div className="group-empty">{group.items.length ? '当前筛选下暂无匹配资源，可切换到“全部平台”和“全部类型”。' : job && isRunning(job) ? '仍在查找，结果将在完成后逐步出现。' : job?.status === 'cancelled' ? '取消前尚未保存匹配资源，不能判断是否存在合适课程。' : job?.status === 'failed' ? '搜索服务未成功返回结果，不能判断是否存在合适课程。' : job?.status === 'interrupted' ? '任务中断前未保存匹配资源。' : job?.status === 'partial' ? '当前有限搜索范围内暂无符合条件的课程。' : '本次检索未找到符合条件的课程。可以调整知识点或语言后再试。'}</div> : visibleItems.map(item => <ResourceCard key={item.resource.resource_id} item={item} points={pointMap.get(item.resource.resource_id) || [group.text]}/>)}
          {platformItems.length > 0 && platformItems.length < (capabilities?.limits.max_results_per_point || 5) && job && !isRunning(job) && <p className="insufficient-note">{activeFilter === 'all' ? '本次' : '当前平台'}仅找到 {platformItems.length} 个符合条件的候选，未补充未经证实的资源。</p>}
        </section>;
      })}</div>
      {!!results.search_attempts.length && <details className="task-records"><summary>查看实际查询记录（{results.search_attempts.length}）</summary><div className="query-records">{results.search_attempts.map((attempt, index) => <div key={index}><strong>{attempt.query}</strong><p>{attempt.provider} · {attempt.status} · {attempt.candidate_count} 个候选{attempt.error_code ? ` · ${attempt.error_code}` : ''}</p>{attempt.cache_hit && <p>{attempt.stale ? '过期缓存' : '缓存'}：{dateLabel(attempt.cached_at)}</p>}</div>)}</div></details>}
    </>}
    {!results && <div className="empty-state"><SearchIcon/><h3>{jobId ? '正在读取任务' : '从一个知识点开始'}</h3><p>搜索结果将在这里逐步出现</p><span>页面信息、访问条件与内容覆盖分别标注。</span></div>}
    <div className="principles"><span>真实来源链接</span><span>未知信息如实标注</span><span>跳转原平台学习</span></div>
  </section>;
}
