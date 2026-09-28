import {
  ApprovalResponse,
  EvalMetrics,
  HealthCheckResponse,
  PipelineRunResponse,
  RejectionResponse,
  Theme,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const API_PREFIX = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${API_PREFIX}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    ...init,
  });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      // response body was not JSON; keep the status-derived message
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

export function fetchThemes(): Promise<Theme[]> {
  return request<Theme[]>('/themes');
}

export function fetchMetrics(): Promise<EvalMetrics> {
  return request<EvalMetrics>('/metrics/eval');
}

export function fetchHealth(): Promise<HealthCheckResponse> {
  return request<HealthCheckResponse>('/health');
}

export function approveTheme(themeId: string, pmUserId: string): Promise<ApprovalResponse> {
  return request<ApprovalResponse>(`/themes/${themeId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ pm_user_id: pmUserId }),
  });
}

export function rejectTheme(themeId: string, pmUserId: string): Promise<RejectionResponse> {
  return request<RejectionResponse>(
    `/themes/${themeId}/reject?pm_user_id=${encodeURIComponent(pmUserId)}`,
    { method: 'POST' },
  );
}

export function triggerPipeline(): Promise<PipelineRunResponse> {
  return request<PipelineRunResponse>('/pipeline/run', {
    method: 'POST',
    body: JSON.stringify({ batch_size: 300, min_cluster_size: 4, min_samples: 2 }),
  });
}
