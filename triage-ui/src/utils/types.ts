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
  cited_quotes?: { quote_text: string; customer_id?: string; customer_tier?: string; arr_value?: number }[];
};

export type ProjectSource = {
  id: string;
  name: string;
  kind: 'meeting' | 'document' | 'drive';
  createdAt: string;
  content: string;
  syncState?: 'local' | 'synced' | 'pending';
};

export type Project = { id: string; name: string; repo?: string; driveFolder?: string; sources: ProjectSource[] };
