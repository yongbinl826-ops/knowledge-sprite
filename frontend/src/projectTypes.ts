import type { Capability, Platform, ResultGroup, SearchPipeline, SearchRequest } from './types';

export type ProjectInput = Omit<SearchRequest, 'knowledge_points'> & { name: string; requirements: string };
export type ProjectSelection = 'learn' | 'mastered' | 'skip';
export type ProjectFunction = { id: string; name: string; original_requirement: string; acceptance_criteria: string; no_new_learning_reason: string | null };
export type ProjectKnowledgePoint = {
  id: string; name: string; description: string; selection: ProjectSelection;
  // Historical metadata is retained for lossless reads/edits, never used to
  // prescribe learning dependencies or reorder the returned concept array.
  readonly function_ids?: string[]; readonly why_needed?: string;
  readonly learning_goal?: string; readonly necessity?: 'required' | 'extension';
  readonly prerequisite_ids?: string[]; readonly learning_order?: number;
  project_task?: string | null; concepts?: string[]; practice_check?: string | null; technology?: string;
  learning_skills?: string[];
};
export type ProjectAnalysis = { analysis_format?: 'concept_list_v1'; scope: string; technical_plan: string; assumptions: string[]; readonly functions?: ProjectFunction[]; knowledge_points: ProjectKnowledgePoint[]; learner_profile?: { student_level: string; assumed_knowledge: string[]; adjustment_note: string } | null };
export type ProjectBatch = { batch_id: string; status: string; project_knowledge_point_ids: string[]; job_id?: string | null; job_status?: string; error?: string | { message?: string; code?: string } | null; warnings?: string[]; errors?: { message: string; code?: string }[] };
export type ProjectVersion = {
  version: number; status: string; input: ProjectInput; analysis: ProjectAnalysis | null;
  confirmation: { version?: number; confirmed_at?: string; [key: string]: unknown } | null;
  batches: ProjectBatch[]; error: string | { message?: string; code?: string } | null;
  budgets?: { max_batches?: number; max_search_requests?: number; max_detail_pages?: number; deadline_seconds?: number };
  created_at: string; model?: string; prompt_version?: string;
  warnings?: string[];
};
export type ProjectSummary = { project_id: string; name: string; current_version: number; created_at: string; updated_at: string };
export type ProjectPointResult = { project_knowledge_point_id: string; name: string; selection: ProjectSelection; status: string; batch_id: string | null; job_id: string | null; knowledge_point_id: string | null; result: ResultGroup | null };
export function hasProjectScopeMismatch(point: Pick<ProjectPointResult, 'status' | 'result'> | undefined): boolean {
  return point?.status === 'scope_mismatch' || point?.result?.scope_status === 'mismatch';
}
export type ProjectView = {
  project_id: string; input: ProjectInput; current_version: number;
  pipeline?: SearchPipeline;
  versions: { version: number; status: string; created_at: string }[];
  version: ProjectVersion | null; points?: ProjectPointResult[]; functions?: ProjectFunction[];
};
export type ProjectAnalysisCapability = Capability & { model?: string; prompt_version?: string; max_functions: number; max_knowledge_points: number };
export type ProjectSearchCapability = { recommendation_policy?: 'helpful-video-v1' | 'related-reference-v1'; max_batches: number; max_search_requests: number; max_detail_pages: number; deadline_seconds: number; batch_size: number };
export const emptyProjectInput: ProjectInput = { name: '', requirements: '', student_level: 'any', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] as Platform[] };
export const projectStatusNames: Record<string, string> = {
  draft: '待分析', analyzing: '正在分析', analyzed: '待确认', analysis_failed: '分析失败', confirmed: '已确认',
  pending: '尚未执行', submitted: '正在检索', running: '正在检索', completed: '检索完成', partial: '部分完成',
  failed: '失败', no_results: '无结果', cancelled: '已取消', interrupted: '已中断', budget_exceeded: '超出预算，未执行',
  mastered: '未勾选', skip: '未勾选', not_selected: '未选择检索', not_started: '尚未执行',
  scope_mismatch: '检索范围需重试',
};
