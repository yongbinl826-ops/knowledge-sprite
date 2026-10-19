import type { SearchPipeline } from '../types';
import './SearchPipelineProgress.css';

export function SearchPipelineProgress({ pipeline, displayed }: { pipeline: SearchPipeline; displayed?: number }) {
  const searching = !pipeline.terminal && ['queued', 'searching', 'analyzing'].includes(pipeline.stage);
  const checking = !pipeline.terminal && (pipeline.checking > 0 || pipeline.stage === 'checking');
  return <div className="search-pipeline" role="status" aria-label="搜索与匹配进度" aria-live="polite" aria-atomic="true">
    <ol className="search-pipeline-steps">
      <li className={searching ? 'active' : ''}><span className="pipeline-number" aria-hidden="true">1</span><div><strong>搜索候选</strong><span>{pipeline.candidates} 条候选{pipeline.search_budget > 0 ? ` · ${pipeline.search_requests}/${pipeline.search_budget} 次搜索` : ''}</span></div></li>
      <li className={checking ? 'active' : ''}><span className="pipeline-number" aria-hidden="true">2</span><div><strong>匹配与大纲校验</strong><span>{pipeline.terminal ? '本次校验结束' : `正在校验 ${pipeline.checking} 条`} · 已过滤 {pipeline.filtered} 条{pipeline.unknown > 0 ? ` · 覆盖待确认 ${pipeline.unknown} 条` : ''}</span></div></li>
      <li className="displayed"><span className="pipeline-number" aria-hidden="true">3</span><div><strong>已显示 {displayed ?? pipeline.displayed} 条</strong><span>{pipeline.terminal ? '本次结果已保留' : '找到后陆续显示'}</span></div></li>
    </ol>
    {pipeline.source_limited && <p className="pipeline-limit">部分来源已限流，已找到的结果继续保留。</p>}
  </div>;
}
