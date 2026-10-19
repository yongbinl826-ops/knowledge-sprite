import { useState } from 'react';
import { platformNames } from '../api';
import { groupItems, resultSections, visibleGroupItems } from '../topicEvidence';
import type { Capabilities } from '../types';
import { hasProjectScopeMismatch, projectStatusNames, type ProjectPointResult, type ProjectVersion } from '../projectTypes';
import { ResourceCard } from './ResourceCard';
import { LearningCoverage } from './LearningCoverage';

export function ProjectResults({ version, points, capabilities, onCancel, onRetry, busy, topic, current }: { version: ProjectVersion; points: ProjectPointResult[]; capabilities: Capabilities | null; onCancel: () => void; onRetry: () => void; busy: boolean; topic: string; current: boolean }) {
  const [filter, setFilter] = useState('all');
  const analysis = version.analysis!;
  const platforms = [...new Set(points.flatMap(point => point.result && !hasProjectScopeMismatch(point) ? [...resultSections.flatMap(section => Object.keys(point.result![section.platforms] || {})), ...groupItems(point.result).map(item => item.resource.platform)] : []))];
  const activeFilter = platforms.includes(filter) ? filter : 'all';
  const byId = new Map(points.map(point => [point.project_knowledge_point_id, point]));
  const groups = [...analysis.functions.map(task => ({ id: task.id, name: task.name, ids: analysis.knowledge_points.filter(point => point.function_ids[0] === task.id && point.selection === 'learn' && (topic === 'all' || topic === point.id)).sort((a,b) => a.learning_order - b.learning_order).map(point => point.id) })), { id: 'prerequisites', name: '公共前置知识', ids: analysis.knowledge_points.filter(point => !point.function_ids.length && point.selection === 'learn' && (topic === 'all' || topic === point.id)).map(point => point.id) }].filter(group => group.ids.length);
  const budgets = version.budgets || capabilities?.project_search;
  const notices = [...new Set([...(version.warnings || []), ...version.batches.flatMap(batch => [...(batch.warnings || []), ...(batch.errors || []).map(error => error.message)])])];
  return <section className="panel results-panel project-results" aria-labelledby="project-results-title"><div className="section-heading"><div><h2 id="project-results-title" aria-label={`项目课程结果 · v${version.version}`}>推荐视频</h2><p>从一个学习单元开始，将学到的内容用在项目里。</p></div><span className={`job-status status-${version.status}`}>{projectStatusNames[version.status] || version.status}</span></div>
    {version.status === 'running' && <div className="search-progress"><span>正在执行项目检索，刷新页面可恢复。</span><button className="text-button" disabled={busy} onClick={onCancel}>取消项目检索</button></div>}
    <details className="search-diagnostics"><summary>查看检索进度与预算</summary>{version.batches.length > 0 && <div className="project-batches" aria-label="项目检索批次">{version.batches.map((batch, index) => <div key={batch.batch_id}><strong>第 {index + 1} 批</strong><span className={`job-status status-${batch.status}`}>{projectStatusNames[batch.status] || batch.status}</span><span>{batch.project_knowledge_point_ids?.length || 0} 个知识点</span>{batch.error && <p>{typeof batch.error === 'string' ? batch.error : batch.error.message || '此批执行失败'}</p>}</div>)}</div>}
    {budgets && <p className="field-help">本版本项目总预算：最多 {budgets.max_search_requests} 次搜索、{budgets.max_detail_pages} 个详情页、{budgets.deadline_seconds} 秒；同时受现有来源访问限制约束。</p>}
    </details>{version.status === "running" && !points.some(point => point.result && groupItems(point.result).length) && <div className="result-skeletons" aria-hidden="true">{[1,2,3].map(index => <div className="skeleton-card" key={index}><div/><i/><i/></div>)}</div>}
    {platforms.length > 1 && <div className="results-toolbar"><label htmlFor="project-platform-filter">项目课程来源</label><select id="project-platform-filter" value={activeFilter} onChange={event => setFilter(event.target.value)}><option value="all">全部平台</option>{platforms.map(platform => <option key={platform} value={platform}>{platformNames[platform] || platform}</option>)}</select></div>}
    {groups.map(group => <section className="project-result-function" key={group.id}><h3>{group.name}</h3>{group.ids.map(id => {
      const point = byId.get(id);
      const planned = analysis.knowledge_points.find(item => item.id === id)!;
      const scopeMismatch = hasProjectScopeMismatch(point);
      const rows = point?.result && !scopeMismatch ? visibleGroupItems(point.result, activeFilter, 'learning', point.result.section_limit || capabilities?.limits.max_results_per_point || 5) : [];
      const status = scopeMismatch ? 'scope_mismatch' : point?.status || (planned.selection === 'learn' ? 'not_started' : planned.selection);
      const emptyMessage = planned.selection !== 'learn' ? '未勾选，不参与搜索。'
        : status === 'pending' || status === 'not_started' ? '尚未执行，知识点仍保留在项目中。'
        : activeFilter !== 'all' && point?.result ? '当前平台下暂无可展示课程，可切换到全部平台。'
        : status === 'partial' ? '本次检索部分完成，未找到可展示的课程。'
        : status === 'no_results' || status === 'completed' ? '本次没有找到可展示的相关课程。'
        : status === 'failed' || status === 'interrupted' ? '这一批未完成，其他批次的有效结果仍保留。'
        : status === 'cancelled' ? '已取消，未取得课程。'
        : status === 'budget_exceeded' ? '项目预算不足，尚未执行；此知识点没有被丢弃。'
        : status === 'submitted' || status === 'running' ? '正在读取或查找课程…' : '当前没有可展示的课程。';
      const manualSearch = `https://search.bilibili.com/all?${new URLSearchParams({ keyword: planned.name })}`;
      const canSearchPlatform = !rows.length && activeFilter === 'all' && version.status !== 'running' && version.input.preferred_platforms.includes('bilibili') && ['partial','no_results','completed','failed','interrupted','cancelled','budget_exceeded'].includes(status);
      return <section className="result-group project-result-point" key={id}><div className="group-heading"><h4>{planned.name}</h4><span>{projectStatusNames[status] || status} · {rows.length} 条推荐</span></div>{scopeMismatch ? <div className="group-empty scope-mismatch-notice" role="status" aria-label="检索范围需重试">
        <p>{point?.result?.scope_notice || '本次检索范围与本单元声明的技术不一致，相关材料已隐藏，请重新检索。'}</p>
        {point?.result?.expected_search_text && <p>需要检索的学习范围：{point.result.expected_search_text}</p>}
        <p>{!current ? '当前为历史结果。请从「我的项目」返回最新版本，再重新检索。' : version.status === 'running' ? '其他单元检索结束后，使用下方「重新检索这些知识点」创建新版本重试。' : '请使用下方「重新检索这些知识点」创建新版本，按当前学习范围重新查找。'}</p>
      </div> : <><LearningCoverage planned={planned} result={point?.result} rows={rows} filtered={activeFilter !== 'all'} searching={['pending','queued','submitted','running'].includes(status)}/>{!rows.length && <p className="group-empty">{emptyMessage}</p>}</>}{canSearchPlatform && <a className="platform-search-fallback" href={manualSearch} target="_blank" rel="noopener noreferrer">到 B站搜索这个单元 <span aria-hidden="true">↗</span><span className="sr-only">（平台搜索入口，非已推荐视频，在新窗口打开）</span></a>}
        {resultSections.map(section => { const selected = rows.filter(row => row.status === section.status); return selected.length ? <section className={`topic-section section-${section.status}`} key={section.status} aria-label={section.label}>{section.status !== 'supported' && <p className="section-caption">{section.status === 'partial' ? '部分匹配 · 可补充学习' : '待核实 · 供参考'}</p>}<div className="course-grid">{selected.map(({ item, status: placement }) => <ResourceCard key={item.resource.resource_id} item={item} placement={placement} points={[planned.name]}/>)}</div></section> : null; })}
      </section>;
    })}</section>)}
    {version.status !== 'running' && <div className="results-next"><p>章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。</p>{current ? <><button className="secondary-button" disabled={busy} onClick={onRetry}>重新检索这些知识点 <span aria-hidden="true">↗</span></button><p className="field-help">重新检索会创建新版本，上次结果保留；受相同预算与限流约束。</p></> : <p className="field-help">正在查看历史结果；返回最新版本后可重新检索。</p>}</div>}
    {notices.length > 0 && <details className="task-records"><summary>本次项目查找说明</summary><ul>{notices.map((notice, index) => <li key={index}>{notice}</li>)}</ul></details>}
  </section>;
}
