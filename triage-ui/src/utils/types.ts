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

export type Project = { id: string; name: string; repo?: string; driveFolder?: string; sources: ProjectSource[] };

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
export type UploadedSource = { id: string; title: string; path?: string | null; mime_type?: string | null; created_at?: string | null; passages: number };
export type UploadFileResult = {
  filename: string;
  status: 'imported' | 'duplicate' | 'skipped' | 'failed';
  detail?: string;
  passages: number;
  sources: UploadedSource[];
  skipped: { path: string; reason: string }[];
};
export type UploadResult = { project_id: string; files: UploadFileResult[]; sources_created: number; passages_created: number };
