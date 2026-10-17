import { useState } from 'react';
import { platformNames, statusNames } from '../api';
import type { Capabilities, SearchJob, SearchResults } from '../types';
import { ResourceCard } from './ResourceCard';
import { SearchIcon } from './Icons';
import { groupItems, resultSections, visibleGroupItems } from '../topicEvidence';

type Props = { capabilities: Capabilities | null; capabilityError: string; job: SearchJob | null; results: SearchResults | null; jobId: string; error: string; notice: string; canCancel: boolean; cancelling: boolean; onCancel: () => void; onRetry: () => void; onRefresh: () => void };
export function ResultsPanel({ capabilities, capabilityError, job, results, jobId, error, notice, canCancel, cancelling, onCancel, onRetry, onRefresh }: Props) {
  const [filter, setFilter] = useState('all');
  const platforms = [...new Set(results?.groups.flatMap(group => [...resultSections.flatMap(section => Object.keys(group[section.platforms] || {})), ...groupItems(group).map(item => item.resource.platform)]) || [])];
  const activeFilter = platforms.includes(filter) ? filter : 'all';
  const warnings = [...new Set([...(job?.warnings || []), ...(results?.warnings || [])])];
  const searching = job && ['queued', 'running'].includes(job.status);
  const serviceUnavailable = ['unconfigured', 'fault'].includes(capabilities?.search.status || '');
  return <section className="results-panel panel" aria-labelledby="results-title">
    <div className="section-heading"><div><h2 id="results-title">推荐课程</h2><p>找到对应章节，去原平台学习</p></div>{job && <span className={`job-status status-${job.status}`}>{statusNames[job.status]}</span>}</div>
    {capabilityError && <div className="notice error-notice" role="alert"><strong>暂时无法连接服务</strong><p>{capabilityError}</p><button className="text-button" onClick={onRefresh}>重新连接</button></div>}
    {serviceUnavailable && <div className="notice warning-notice"><strong>搜索服务暂不可用</strong><p>{capabilities?.search.message}</p></div>}
    {error && <div className="notice error-notice" role="alert"><strong>请求未完成</strong><p>{error}</p>{jobId && <button className="text-button" onClick={onRetry}>重新读取结果</button>}</div>}
    {notice && <p className="action-notice" role="status">{notice}</p>}
    {searching && <div className="search-progress" aria-live="polite"><span>{job.phase === 'queued' ? '正在排队…' : `正在查找课程与匹配章节 · ${job.progress.queries_completed}/${job.progress.queries_planned || '—'}`}</span>{canCancel && <button className="text-button" disabled={cancelling} onClick={onCancel}>{cancelling ? '正在取消…' : '取消'}</button>}</div>}
    {job?.status === 'partial' && <p className="result-notice">已找到以下课程，部分来源尚未完成核验。</p>}
    {job?.status === 'cancelled' && <p className="result-notice">已取消查找，保留已找到的课程。</p>}
    {job?.status === 'interrupted' && <p className="result-notice">查找已中断，可重新提交；已找到的课程仍可查看。</p>}
    {job?.status === 'failed' && <p className="notice error-notice" role="alert">本次搜索未能完成，请稍后重试。</p>}
    {results && <>
      {platforms.length > 1 && <div className="results-toolbar"><label htmlFor="platform-filter">来源平台</label><select id="platform-filter" value={activeFilter} onChange={e => setFilter(e.target.value)}><option value="all">全部平台</option>{platforms.map(platform => <option key={platform} value={platform}>{platformNames[platform] || platform}</option>)}</select></div>}
      <div className="result-groups">{results.groups.map(group => {
        const limit = group.section_limit && group.section_limit > 0 ? group.section_limit : capabilities?.limits.max_results_per_point || 5;
        const items = visibleGroupItems(group, activeFilter, 'learning', limit);
        return <section className="result-group" key={group.knowledge_point_id} aria-labelledby={`group-${group.knowledge_point_id}`}>
          <div className="group-heading"><h3 id={`group-${group.knowledge_point_id}`}>{group.text}</h3><span>{items.length} 条推荐</span></div>
          {!items.length && <p className="group-empty">{activeFilter !== 'all' ? '当前平台下暂无课程，可切换到全部平台。' : searching ? '正在查找相关课程…' : job?.status === 'completed' ? '本次没有找到相关课程，试试调整知识点。' : '当前范围内暂无课程，稍后可重试或切换平台。'}</p>}
          {resultSections.map(section => {
            const rows = items.filter(row => row.status === section.status);
            if (!rows.length) return null;
            return <section className={`topic-section section-${section.status}`} key={section.status} aria-label={section.label}>
              {section.status !== 'supported' && <p className="section-caption">{section.status === 'partial' ? '部分匹配 · 可补充学习' : '待核实 · 供参考'}</p>}
              <div className="course-grid">{rows.map(({ item, status }) => <ResourceCard key={item.resource.resource_id} item={item} placement={status} points={[group.text]}/>)}</div>
            </section>;
          })}
        </section>;
      })}</div>
    </>}
    {!results && <div className="empty-state"><SearchIcon/><h3>{jobId ? '正在寻找学习资源' : '想学什么？'}</h3><p>输入知识点，找到课程和对应章节</p></div>}
    {(warnings.length > 0 || !!job?.errors.length) && <details className="task-records"><summary>本次查找说明</summary><ul>{warnings.map((warning, index) => <li key={`w${index}`}>{warning}</li>)}{job?.errors.map((record, index) => <li key={`e${index}`}>{record.message}</li>)}</ul></details>}
  </section>;
}
