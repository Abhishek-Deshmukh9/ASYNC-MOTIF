export type ScoreSignal = {
  key: string; label: string; raw: number; display: string; percentile: number; weight: number; points: number;
  evidence: Record<string, unknown>[]; why: string; how: string;
  value?: string; note?: string; max_points?: number; // short form for the theme card
};

export type ScoreBreakdown = {
  version: number; profile: string; profile_label: string; priority_score: number; rank: number; of: number; verdict: string;
  signals: ScoreSignal[];
  dropped: { key: string; label: string; reason: string; short?: string }[];
  confidence: { cohesion: number; verified_quotes: number; mentions: number; level: 'supported' | 'thin' };
};

export type Theme = {
  id: string;
  cluster_id: number;
  title: string;
  summary: string;
  revenue_at_risk: number;
  affected_accounts_count: number;
  status: string;
  prd_markdown?: string | null;
  github_issue_url?: string | null;
  github_issue_number?: number | null;
  cited_quotes?: { quote_text: string; customer_id?: string | null; customer_tier?: string | null; arr_value?: number; source_name?: string | null }[];
  priority_score?: number | null; // 0-100, built from the signals in score_breakdown
  score_breakdown?: ScoreBreakdown | null;
  activity?: ThemeActivity[];
  mention_count?: number; // passages grouped into this theme
  source_count?: number; // distinct uploaded sources among them
};

export type ProjectSource = {
  id: string;
  name: string;
  kind: 'meeting' | 'document' | 'drive';
  createdAt: string;
  content: string;
  syncState?: 'local' | 'synced' | 'pending';
  serverId?: string; // id of the source on the backend, once uploaded
  passages?: number; // how many passages the backend split it into
};

export type ProjectRole = 'owner' | 'editor' | 'viewer';
export type ServerProject = { id: string; name: string; github_repo: string | null; created_at: string | null; role?: ProjectRole; owner_email?: string | null };

// Teammates on a project (GET /projects/{id}/members)
export type Member = { id: string; email: string; role: 'editor' | 'viewer'; status: 'joined' | 'invited'; invited_by?: string | null; joined_at?: string | null };
export type MemberList = { owner_email: string | null; my_role: ProjectRole; members: Member[] };

// Who approved, edited or rejected a theme, newest first
export type ThemeActivity = { action: string; by: string; at: string | null; title?: string | null; changed_title?: boolean };

export type Project = { id: string; name: string; repo?: string; driveFolder?: string; sources: ProjectSource[]; role?: ProjectRole; ownerEmail?: string | null };

// Benchmark metrics from GET /api/v1/metrics/eval. A metric is null when there is nothing
// to measure yet (no themes, no PM decisions, no quotes, or no ground-truth labels).
export type EvalMetrics = {
  project_id: string | null;
  precision_at_3: number | null;
  target_precision_at_3: number;
  ground_truth_top_3: string[];
  top_3_breakdown: { title: string; matched_ground_truth_theme: string | null; purity: number; is_in_ground_truth_top_3: boolean }[];
  acceptance_rate: number | null;
  target_acceptance_rate: number;
  pm_decisions_count: number;
  citation_validity: number | null;
  target_citation_validity: number;
  verified_quotes_count: number;
  total_quotes_count: number;
  total_feedback_items: number;
  total_themes_discovered: number;
  approved_themes_count: number;
  rejected_themes_count: number;
  pending_themes_count: number;
  total_revenue_at_risk: number;
};

export type ApprovalResult = {
  github_issue_url?: string | null;
  github_issue_number?: number | null;
  github_dispatch?: 'live' | 'simulated';
  github_message?: string | null;
  prd_markdown?: string | null;
};

// A source stored on the backend (POST /sources/upload, GET /sources)
export type UploadedSource = { id: string; title: string; path?: string | null; mime_type?: string | null; created_at?: string | null; passages: number; connection_id?: string | null; url?: string | null };
export type UploadFileResult = {
  filename: string;
  status: 'imported' | 'duplicate' | 'skipped' | 'failed';
  detail?: string;
  passages: number;
  sources: UploadedSource[];
  skipped: { path: string; reason: string }[];
};
export type UploadResult = { project_id: string; files: UploadFileResult[]; sources_created: number; passages_created: number };

export type ProviderId = 'notion' | 'gdrive' | 'slack' | 'github';
export type Connection = {
  id: string; provider: ProviderId; label: string; project_id: string; display_name?: string | null;
  config: { page_ids?: string[]; folder_id?: string; channel_ids?: string[]; [key: string]: unknown };
  status: 'active' | 'syncing' | 'error'; last_synced_at?: string | null; last_error?: string | null;
  last_result?: { imported: number; updated: number; unchanged: number; removed: number; failed: number; passages: number } | null;
  sources: number;
};
export type ConnectionOption = { id: string; name: string; is_member?: boolean };
export type SyncResult = { imported: number; updated: number; unchanged: number; skipped: number; failed: number; removed: number; passages: number; errors: string[] };
