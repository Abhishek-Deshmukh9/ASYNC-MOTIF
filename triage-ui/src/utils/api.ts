import { ApprovalResult, EvalMetrics, ProjectSource, Theme } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const fetchThemes = (projectId?: string) => request<Theme[]>(`/themes${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`);
const scopeQuery = (projectId?: string) => (projectId ? `?project_id=${encodeURIComponent(projectId)}` : '');
// projectId undefined = the labelled demo corpus loaded by seed.py
export type PipelineResult = { themes_created?: number; duration_seconds?: number; project_id?: string | null; [key: string]: unknown };
export const runPipeline = (projectId?: string) => request<PipelineResult>('/pipeline/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch_size: 100, project_id: projectId ?? null }) });
export const fetchMetrics = (projectId?: string) => request<EvalMetrics>(`/metrics/eval${scopeQuery(projectId)}`);
export const approveTheme = (id: string, title?: string, repo?: string, summary?: string) => request<ApprovalResult>(`/themes/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pm_user_id: 'workspace_user', ...(title ? { final_title: title } : {}), ...(summary ? { final_summary: summary } : {}), ...(repo ? { github_repo: repo } : {}) }) });
export const rejectTheme = (id: string) => request<{ status: string }>(`/themes/${id}/reject?pm_user_id=workspace_user`, { method: 'POST' });
export const fetchPipelineStatus = () => request<PipelineProgress>('/pipeline/status');
export const seedDemoCorpus = () => request<{ seeded: boolean; total_items: number; message: string }>('/health/seed', { method: 'POST' });

export async function ingestSource(source: ProjectSource, projectId: string) {
  const file = new File([JSON.stringify([{
    source_type: source.kind === 'meeting' ? 'meeting_transcript' : 'google_drive',
    external_id: `motif_${source.id}`,
    content: source.content,
    customer_tier: 'free',
    metadata: { project_id: projectId, source_name: source.name },
  }])], `${source.name.replace(/[^a-z0-9-_]/gi, '_')}.json`, { type: 'application/json' });
  const form = new FormData();
  form.append('file', file);
  return request<{ canonical_persisted_count: number }>('/feedback/upload', { method: 'POST', body: form });
}

// Pipeline progress tracking via SSE
export type PipelineProgress = {
  status: string;
  stage: string;
  stage_detail: string;
  percent: number;
  elapsed_seconds: number | null;
  error: string | null;
  last_result: PipelineResult | null;
};

export function subscribeToPipelineProgress(
  onMessage: (data: PipelineProgress) => void,
  onError?: () => void,
): () => void {
  const source = new EventSource('/api/v1/pipeline/progress');
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as PipelineProgress;
      onMessage(data);
    } catch {
      // ignore parse errors
    }
  };
  source.onerror = () => {
    onError?.();
    source.close();
  };
  return () => source.close();
}
