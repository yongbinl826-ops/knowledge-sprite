import { useEffect, useState } from 'react';
import type { SearchPipeline } from '../types';
import './SearchPipelineProgress.css';

type ProgressProps = { pipeline: SearchPipeline; displayed?: number };

export function ProjectSearchProgress(props: ProgressProps) {
  const [scrolled, setScrolled] = useState(() => window.scrollY > 0);
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 0);
    update();
    window.addEventListener('scroll', update, { passive: true });
    return () => window.removeEventListener('scroll', update);
  }, []);
  return props.pipeline.terminal ? null : <div className="project-progress" data-scrolled={scrolled}><SearchPipelineProgress {...props}/></div>;
}

export function SearchPipelineProgress({ pipeline, displayed }: ProgressProps) {
  if (pipeline.terminal) return null;
  let phase: string;
  if (pipeline.stage === 'analyzing') {
    phase = '正在分析知识点';
  } else if (pipeline.stage === 'checking') {
    phase = pipeline.source_limited ? '来源受限，正在校验' : '正在校验视频与大纲';
  } else if (pipeline.stage === 'queued') {
    phase = '正在准备搜索';
  } else {
    phase = pipeline.source_limited ? '来源受限，继续搜索' : '正在搜索相关视频';
  }
  const description = `${phase} · 已显示 ${displayed ?? pipeline.displayed} 条`;
  return <div className="search-pipeline" data-state="active" role="status" aria-label="搜索与匹配进度" aria-live="polite" aria-atomic="true">
    <div className="pipeline-bar" role="progressbar" aria-label="搜索与匹配进度" aria-valuemin={0} aria-valuemax={100} aria-valuetext={description}>
      <span className="pipeline-bar-fill"/>
    </div>
    <p className="pipeline-description">{description}</p>
  </div>;
}
