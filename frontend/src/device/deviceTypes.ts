import type { ProjectAnalysis, ProjectInput, ProjectSummary, ProjectView } from '../projectTypes';
import type { SearchRequest, SearchResults } from '../types';

export type MobileTaskBody = { kind: 'analysis'; input: ProjectInput } | {
  kind: 'search'; input: ProjectInput; analysis: ProjectAnalysis; reviewed_topic_technologies: Record<string, string>;
} | { kind: 'direct_search'; request: SearchRequest };
export type MobileTask = {
  snapshot_revision?: string;
  task_id: string; kind: MobileTaskBody['kind']; expires_at: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  error: null | { code: string; message: string }; result: ProjectView | SearchResults | null;
};
export type TaskTicket = {
  schema: 1; id: string; capability: string; body: string; projectId: string; version: number;
  createdAt: string; expiresAt: string; phase: 'prepared' | 'submitted' | 'uncertain' | 'complete' | 'expired';
  nextPollAt?: string; message?: string; snapshotRevision?: string;
};
export type LocalProject = { schema: 1; mode?: 'project' | 'direct'; summary: ProjectSummary; input: ProjectInput; views: ProjectView[];
  drafts: Record<number, ProjectAnalysis>; learned: Record<string, { learned: boolean; at: string }>; ticket?: TaskTicket };
export type DeviceState = { schema: 1; revision: number; projects: Record<string, LocalProject>;
  selected: { id: string; version?: number }; inputDraft: ProjectInput | null };
export type PublicCourse = { course_id: string; url: string; title: string; platform: string;
  thumbnail_url?: string | null; author?: string | null; resource_type: string;
  observed_at: string; expires_at: string; access_notice?: string | null };
export type CoursePage = { items: PublicCourse[]; total: number; has_more: boolean };
