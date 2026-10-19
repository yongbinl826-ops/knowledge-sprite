import type { VisibleItem } from '../topicEvidence';
import type { ResultGroup } from '../types';
import type { ProjectKnowledgePoint } from '../projectTypes';
import { LegacyLearningCoverage } from './LegacyLearningCoverage';
import { SkillLearningRoute } from './SkillLearningRoute';

export function LearningCoverage(props: {
  planned: ProjectKnowledgePoint; result: ResultGroup | null | undefined; rows: VisibleItem[];
  filtered: boolean; searching: boolean; prerequisites?: string[];
}) {
  return <SkillLearningRoute {...props} legacy={<details className="legacy-requirements">
    <summary>原项目要求来源核对 <span>旧口径明细</span></summary>
    <p className="field-help">这里逐项保留原要求与来源的核对结果；它不表示课程没有学习价值，也不是项目实践完成度。</p>
    <LegacyLearningCoverage {...props}/>
  </details>}/>;
}
