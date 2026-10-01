import { getAccessToken } from './supabase';
import { ApprovalResult, Connection, ConnectionOption, InboxItem, InboxMessage, InboxState, Member, MemberList, ProviderId, SyncResult, EvalMetrics, ProjectSource, ServerProject, Theme, UploadResult, UploadedSource } from './types';

export const SIGN_IN_REQUIRED = 'motif:sign-in-required';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/api/v1${path}`, { ...init, headers });
  if (response.status === 401 && token !== null && typeof window !== 'undefined') window.dispatchEvent(new Event(SIGN_IN_REQUIRED));
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const fetchThemes = (projectId?: string) => request<Theme[]>(`/themes${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`);
const scopeQuery = (projectId?: string) => (projectId ? `?project_id=${encodeURIComponent(projectId)}` : '');
// projectId undefined = the labelled demo corpus loaded by seed.py
export type PipelineProgress = { status: 'idle' | 'running' | 'failed'; stage: 'embedding' | 'clustering' | 'labelling' | 'saving' | null; done: number; total: number; elapsed_seconds: number | null; error: string | null; last_result: PipelineResult | null };
export type PipelineResult = { themes_created?: number; duration_seconds?: number; project_id?: string | null; [key: string]: unknown };
const pipelineStatus = (projectId?: string) => request<PipelineProgress>(`/pipeline/status${scopeQuery(projectId)}`);
// projectId undefined = the labelled demo corpus loaded by seed.py.
// The run happens on the server in the background; this polls its progress and resolves with the result.
export async function runPipeline(projectId?: string, onProgress?: (progress: PipelineProgress) => void, profile?: string): Promise<PipelineResult> {
  const started = await request<{ status: string }>('/pipeline/run?background=true', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch_size: 100, project_id: projectId ?? null, ...(profile ? { profile } : {}) }) });
  if (started.status !== 'running') throw new Error('The analysis did not start.');
  let failures = 0;
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    let progress: PipelineProgress;
    try { progress = await pipelineStatus(projectId); failures = 0; } catch (cause) {
      if (++failures >= 5) throw cause; // tolerate brief hiccups; give up if the API stays unreachable
      continue;
    }
    onProgress?.(progress);
    if (progress.status === 'failed') throw new Error(progress.error || 'The analysis failed.');
    if (progress.status === 'idle' && progress.last_result) return progress.last_result;
  }
}
export const fetchMetrics = (projectId?: string) => request<EvalMetrics>(`/metrics/eval${scopeQuery(projectId)}`);
export const approveTheme = (id: string, title?: string, repo?: string, summary?: string) => request<ApprovalResult>(`/themes/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pm_user_id: 'workspace_user', ...(title ? { final_title: title } : {}), ...(summary ? { final_summary: summary } : {}), ...(repo ? { github_repo: repo } : {}) }) });
export const changeIssueType = (id: string, issueType: string) => request<{ rank: number; of: number; priority_score: number }>(`/themes/${id}/type`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ issue_type: issueType }) });
export const rejectTheme = (id: string) => request<{ status: string }>(`/themes/${id}/reject?pm_user_id=workspace_user`, { method: 'POST' });
export const fetchPipelineStatus = (projectId?: string) => pipelineStatus(projectId);

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

// The signed-in user's projects, kept on the server so they follow the account
export const fetchProjects = () => request<ServerProject[]>('/projects');
export const saveProject = (project: { id: string; name: string; repo?: string }) =>
  request<ServerProject>('/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: project.id, name: project.name, github_repo: project.repo || null }) });

// Connected tools (Notion, Google Drive, Slack)
const json = (body: unknown): RequestInit => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const fetchConnections = (projectId: string) => request<Connection[]>(`/connections?project_id=${encodeURIComponent(projectId)}`);
export const createConnection = (projectId: string, projectName: string, provider: ProviderId, credentials: Record<string, unknown>) =>
  request<Connection>('/connections', { method: 'POST', ...json({ project_id: projectId, project_name: projectName, provider, credentials }) });
export const connectionOptions = (id: string) => request<ConnectionOption[]>(`/connections/${id}/options`);
export const updateConnection = (id: string, config: Record<string, unknown>) => request<Connection>(`/connections/${id}`, { method: 'PATCH', ...json({ config }) });
export const syncConnection = (id: string) => request<SyncResult>(`/connections/${id}/sync`, { method: 'POST' });
export const deleteConnection = (id: string, removeSources: boolean) => request<{ sources_removed: number }>(`/connections/${id}?remove_sources=${removeSources}`, { method: 'DELETE' });

// Team projects: the owner invites teammates by email as editors or viewers
const membersPath = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/members`;
export const fetchMembers = (projectId: string) => request<MemberList>(membersPath(projectId));
export const inviteMember = (projectId: string, email: string, role: 'editor' | 'viewer') => request<Member>(membersPath(projectId), { method: 'POST', ...json({ email, role }) });
export const changeMemberRole = (projectId: string, memberId: string, role: 'editor' | 'viewer') => request<Member>(`${membersPath(projectId)}/${memberId}`, { method: 'PATCH', ...json({ role }) });
export const removeMember = (projectId: string, memberId: string) => request<{ removed: boolean; left: boolean }>(`${membersPath(projectId)}/${memberId}`, { method: 'DELETE' });

// Live inbox: add one message, see which theme it joins; owners can make a secret webhook link for other tools
export const fetchInbox = (projectId?: string) => request<InboxState>(`/inbox${scopeQuery(projectId)}`);
export const sendToInbox = (projectId: string | undefined, message: InboxMessage) =>
  request<InboxItem>('/inbox', { method: 'POST', ...json({ project_id: projectId ?? null, text: message.text, source: message.source, customer: message.customer || null, author: message.author || null }) });
export const createInboxWebhook = (projectId: string) => request<{ token: string; path: string; hint: string }>(`/inbox/webhook?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' });
export const deleteInboxWebhook = (projectId: string) => request<{ enabled: boolean }>(`/inbox/webhook?project_id=${encodeURIComponent(projectId)}`, { method: 'DELETE' });
