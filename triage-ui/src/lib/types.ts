export interface CitedQuote {
  quote_text: string;
  feedback_item_id?: string | null;
  customer_id?: string | null;
  arr_value?: number | null;
  customer_tier?: string | null;
}

export interface Theme {
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
  created_at: string;
  updated_at: string;
  cited_quotes: CitedQuote[];
}

export interface TopThemeBreakdown {
  title: string;
  matched_ground_truth_theme: string | null;
  purity: number;
  is_in_ground_truth_top_3: boolean;
}

// Metrics are null when there is nothing to measure yet (no themes, no PM decisions, no quotes).
export interface EvalMetrics {
  precision_at_3: number | null;
  target_precision_at_3: number;
  ground_truth_top_3: string[];
  top_3_breakdown: TopThemeBreakdown[];
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
}

export interface DatabaseHealth {
  database: string;
  pgvector_extension: string;
  latency_ms?: number | null;
  error?: string | null;
}

export interface HealthCheckResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  database: DatabaseHealth;
}

export interface ApprovalResponse {
  status: string;
  theme_id: string;
  title: string;
  revenue_at_risk: number;
  github_issue_url?: string | null;
  github_issue_number?: number | null;
  github_dispatch?: 'live' | 'simulated';
  github_message?: string | null;
  prd_markdown?: string | null;
  audit_logged: boolean;
}

export interface RejectionResponse {
  status: string;
  theme_id: string;
  audit_logged: boolean;
}

export interface PipelineRunResponse {
  status: string;
  message?: string;
  items_processed: number;
  newly_embedded?: number;
  dense_clusters_count?: number;
  noise_items_isolated?: number;
  themes_created: number;
}
