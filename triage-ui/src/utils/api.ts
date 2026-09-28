import { ProjectSource, Theme } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const fetchThemes = (projectId?: string) => request<Theme[]>(`/themes${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`);
export const runPipeline = (projectId: string) => request<{ themes_created?: number; [key: string]: unknown }>('/pipeline/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch_size: 100, project_id: projectId }) });
export const approveTheme = (id: string, title?: string, repo?: string) => request<{ github_issue_url?: string; github_issue_number?: number; prd_markdown?: string }>(`/themes/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pm_user_id: 'workspace_user', ...(title ? { final_title: title } : {}), ...(repo ? { github_repo: repo } : {}) }) });

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
