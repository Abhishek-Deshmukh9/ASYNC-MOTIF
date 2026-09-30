import { ApprovalResult, EvalMetrics, ProjectSource, Theme, UploadResult, UploadedSource } from './types';

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
export const fetchPipelineStatus = () => request<{ status: string; last_result?: PipelineResult | null }>('/pipeline/status');

// Project sources: files are extracted, split into passages and stored on the backend
export async function uploadSources(files: { file: Blob; name: string }[], projectId: string, projectName?: string, kind: 'document' | 'meeting' = 'document') {
  const form = new FormData();
  form.append('project_id', projectId);
  if (projectName) form.append('project_name', projectName);
  form.append('kind', kind);
  files.forEach(({ file, name }) => form.append('files', file, name));
  return request<UploadResult>('/sources/upload', { method: 'POST', body: form });
}
export const fetchSources = (projectId: string) => request<UploadedSource[]>(`/sources?project_id=${encodeURIComponent(projectId)}`);
export const deleteSource = (id: string, projectId: string) => request<{ deleted: string; passages_removed: number }>(`/sources/${id}?project_id=${encodeURIComponent(projectId)}`, { method: 'DELETE' });

// Send a source written in the browser (a meeting transcript) through the same upload path.
// Returns the backend source id, or null when the same text is already in the project.
export async function ingestSource(source: ProjectSource, projectId: string, projectName?: string): Promise<string | null> {
  const name = /\.(md|markdown|txt)$/i.test(source.name) ? source.name : `${source.name}.md`;
  const file = new Blob([source.content], { type: 'text/markdown' });
  const result = await uploadSources([{ file, name }], projectId, projectName, source.kind === 'meeting' ? 'meeting' : 'document');
  const [first] = result.files;
  if (first?.status === 'failed' || first?.status === 'skipped') throw new Error(`${source.name}: ${first.detail || 'could not be imported'}`);
  return first?.sources[0]?.id ?? null;
}
