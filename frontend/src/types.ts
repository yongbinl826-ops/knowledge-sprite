export type Platform = 'bilibili' | 'icourse163' | 'xuetangx';
export type JobStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'interrupted' | 'cancelled';
export type JobCreated = { job_id: string; status?: JobStatus; reused?: boolean };
export type JobCancelled = { job_id: string; status: JobStatus; cancelled: boolean };
export type SearchRequest = {
  knowledge_points: string[];
  student_level: 'beginner' | 'intermediate' | 'advanced' | 'any';
  language: 'zh' | 'en' | 'any';
  project_context: string;
  technical_version: string;
  preferred_platforms: Platform[];
};
export type Capability = { status: string; message: string };
export type Capabilities = {
  mode: string;
  search: Capability & { selected_provider: string; providers: (Capability & { name: string })[] };
  llm: Capability;
  fetch: Capability & { browser_fallback: boolean; transport?: { phased_timeouts: boolean; initial_timeout_seconds: number; body_idle_timeout_seconds: number; body_min_bytes_per_second: number; body_timeout_cap_seconds: number } };
  js_render?: { enabled: boolean; status: string; allowed_hosts: string[]; allowed_entries?: string[]; asset_hosts: string[];
    timeout_seconds: number; max_resources: number; max_target_requests: number; max_doh_requests: number;
    max_total_bytes: number; max_dom_bytes: number; max_observed_data_resources: number;
    online_browser_fallback: boolean; message: string; process_network_egress: string; playback_verified: boolean };
  platforms: { id: string; name: string; discovery: string; metadata: string; playback: string; policy_status?: string; source_url?: string | null; reviewed_at?: string | null; policy_basis?: string | null; policy_section?: string | null; terms_date?: string | null; effective_at?: string | null; review_method?: string | null }[];
  limits: { max_knowledge_points: number; max_results_per_point: number; max_search_requests: number; max_detail_pages: number };
};
export type SearchJob = {
  job_id: string; status: JobStatus; phase: string;
  created_at: string; updated_at: string; request: SearchRequest;
  progress: { queries_planned: number; queries_completed: number; search_requests: number; search_successes: number; search_failures: number; candidates_discovered: number; resources_discovered: number; details_attempted: number; details_completed: number; details_cached?: number; catalog_pages_attempted?: number; catalog_pages_completed?: number; cache_hits: number };
  budgets: { max_search_requests: number; max_detail_pages: number; deadline_seconds: number };
  warnings: string[]; errors: { code: string; message: string }[];
  knowledge_points: { knowledge_point_id: string; text: string }[];
};
export type CacheInfo = { hit: boolean; cached_at: string | null; stale: boolean };
export type RenderAcquisition = { acquisition?: string; render_id?: string; source_sha256?: string | null; manifest_sha256?: string | null; dom_sha256?: string | null };
export type FieldProvenance = RenderAcquisition & { evidence_id?: string; source?: string; url?: string; fetched_at?: string };
export type RenderDiagnostics = RenderAcquisition & {
  status: string; source_url?: string | null; static_chapter_count?: number | null; rendered_chapter_count?: number | null;
  added_fields?: string[]; page_status?: string; target_requests?: number; doh_requests?: number; total_bytes?: number;
  error?: string | null; elapsed_seconds?: number;
};
export type Chapter = {
  title: string; url?: string | null; evidence_id?: string; source?: string;
  start_seconds?: number | null; end_seconds?: number | null;
  duration_seconds?: number | null;
  field_provenance?: Record<string, FieldProvenance>;
};
export type Resource = {
  resource_id: string; title: string; url: string; canonical_url: string;
  resolved_url?: string | null;
  platform: string; resource_type: string;
  author: string | null; description: string | null; language: string | null;
  thumbnail_url?: string | null;
  author_role?: 'course_instructors' | 'video_instructors' | 'credited_creator' | null;
  duration_seconds: number | null; published_at: string | null; discovered_at: string; fetched_at: string | null;
  fetch_status: string; metadata_evidence_level: string;
  video_evidence_status?: 'search_discovered' | 'page_verified' | 'none';
  requires_login: boolean | null; requires_payment: boolean | null; requires_enrollment: boolean | null;
  chapters: Chapter[]; catalog_kind?: 'course_outline' | 'video_playlist' | 'video_chapters' | 'video_parts' | null; catalog_fetch_status?: string | null; field_provenance: Record<string, unknown>;
  access_notice?: string | null;
  cache?: CacheInfo; playback_verified: boolean;
  parent_course_url?: string | null;
  course_identity?: CourseIdentity;
  render_diagnostics?: RenderDiagnostics | null;
};
export type CourseIdentity = {
  status: 'identified' | 'partial' | 'unknown';
  family_id: string | null; offering_id: string | null; lesson_id: string | null;
  family_url: string | null; offering_url: string | null;
  role: 'course' | 'catalog' | 'lesson' | 'video' | 'unknown';
  basis: 'recognized_url' | 'page_course' | 'page_is_part_of' | 'unknown';
  source_url: string | null; evidence_ids: string[]; unknown_reason: string | null;
};
export type Evidence = RenderAcquisition & {
  evidence_id: string; kind: string; source: string; query?: string;
  url: string; title?: string; snippet?: string; text?: string; field?: string;
  observed_at?: string; fetched_at?: string; reviewed_at?: string; cache?: CacheInfo;
  section?: string | null; terms_date?: string | null; effective_at?: string | null;
  review_method?: string | null; evidence_sha256?: string | null; blocked_target_url?: string | null;
  restricted_target_request_sent?: boolean; restricted_target_http_status?: number | null;
};
export type ResourceItem = {
  resource: Resource;
  match: { knowledge_point_id: string; resource_id: string; ranking_score: number; recommendation_reason: string; matched_evidence_ids: string[]; coverage_basis: string[];
    topic_evidence_status?: TopicEvidenceStatus;
    topic_evidence_reasons?: { code: string; message: string; evidence_ids: string[] }[];
    supporting_evidence_ids?: string[];
    subtopic_coverage?: SubtopicCoverage[];
  };
  evidence: Evidence[];
};
export type TopicEvidenceStatus = 'supported' | 'partial' | 'needs_review';
export type SubtopicCoverage = { id: string; text: string; status: 'supported' | 'unknown'; evidence_ids: string[]; reason: string };
export type CollectionCoverage = {
  decomposition_status: 'applied' | 'not_applicable' | 'unknown'; shared_context: string[];
  status: 'all_subtopics_supported' | 'some_subtopics_supported' | 'unknown';
  subtopics: { id: string; text: string; status: 'supported' | 'unknown'; resource_ids: string[]; evidence_ids: string[] }[];
  single_resource_full_coverage: boolean; disclaimer: string;
};
export type ResultGroup = {
  knowledge_point_id: string; text: string; total_matches: number; items: ResourceItem[]; section_limit?: number;
  platform_items?: Record<string, ResourceItem[]>;
  total_partial_matches?: number; partial_items?: ResourceItem[]; partial_platform_items?: Record<string, ResourceItem[]>;
  total_review_matches?: number; review_items?: ResourceItem[]; review_platform_items?: Record<string, ResourceItem[]>;
  collection_coverage?: CollectionCoverage; platform_collection_coverage?: Record<string, CollectionCoverage>;
};
export type SearchResults = {
  job_id: string; status: JobStatus;
  groups: ResultGroup[];
  warnings: string[];
  identity_summary?: { resource_records: number; identified_course_families: number; identified_course_offerings: number; identified_lessons: number; unknown_course_family_resources: number; unknown_offering_resources: number; unknown_identity_resources: number; scope: string };
  search_attempts: { knowledge_point_id: string; query: string; provider: string; status: string; candidate_count: number; cached_at: string | null; cache_hit: boolean; stale: boolean; error_code?: string }[];
};
