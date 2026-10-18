import { api } from './client.js';

export interface GitConfig {
  id: string;
  company_id: string | null;
  provider: string;
  repo_url: string;
  branch: string;
  sync_interval: number;
  auto_pr: boolean;
  status: string;
  last_synced: string | null;
  last_commit_sha: string | null;
  created_at: string;
}

export interface SyncLog {
  id: string;
  direction: 'pull' | 'push';
  files_changed: number;
  commit_sha: string | null;
  pr_url: string | null;
  status: 'success' | 'error' | 'no_changes';
  message: string | null;
  created_at: string;
}

function qs(company_id?: string) {
  return company_id ? `?company_id=${company_id}` : '';
}

export const git = {
  config:     (company_id?: string) => api.get<GitConfig | null>(`/git/config${qs(company_id)}`),
  connect:    (body: { provider: string; repo_url: string; branch: string; token: string; sync_interval: number; auto_pr: boolean }, company_id?: string) =>
    api.post<GitConfig>(`/git/config${qs(company_id)}`, body),
  update:     (body: Partial<{ branch: string; token: string; sync_interval: number; auto_pr: boolean }>, company_id?: string) =>
    api.patch<GitConfig>(`/git/config${qs(company_id)}`, body),
  disconnect: (company_id?: string) => api.delete(`/git/config${qs(company_id)}`),
  pull:       (company_id?: string) => api.post<SyncLog>(`/git/pull${qs(company_id)}`, {}),
  push:       (message?: string, company_id?: string) => api.post<SyncLog>(`/git/push${qs(company_id)}`, { message: message ?? '' }),
  logs:       (limit = 20, company_id?: string) => api.get<SyncLog[]>(`/git/logs?limit=${limit}${company_id ? `&company_id=${company_id}` : ''}`),
};
