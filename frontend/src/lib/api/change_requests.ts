import { api } from './client';

export type CRStatus =
	| 'submitted'
	| 'dept_head_approved'
	| 'admin_approved'
	| 'committed'
	| 'rejected';

export type ChangeRequest = {
	id: string;
	company_id: string;
	personnel_id: string;
	change_type: 'agent_config' | 'skill' | 'policy' | 'harness';
	title: string;
	proposed: Record<string, unknown>;
	original: Record<string, unknown> | null;
	status: CRStatus;
	dept_head_id: string | null;
	dept_head_approved_at: string | null;
	dept_head_rejected_at: string | null;
	dept_head_note: string | null;
	admin_id: string | null;
	admin_approved_at: string | null;
	admin_rejected_at: string | null;
	admin_note: string | null;
	commit_sha: string | null;
	commit_url: string | null;
	created_by_user_id: string | null;
	created_at: string;
	updated_at: string;
};

export type CRCreate = {
	personnel_id: string;
	change_type: 'agent_config' | 'skill' | 'policy' | 'harness';
	title: string;
	proposed: Record<string, unknown>;
	original?: Record<string, unknown> | null;
};

function qs(params: Record<string, string | undefined>) {
	const p = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v) p.set(k, v);
	}
	return p.toString() ? `?${p}` : '';
}

export const changeRequests = {
	list: (params?: { company_id?: string; status?: string; personnel_id?: string }) =>
		api.get<ChangeRequest[]>(`/change-requests${qs(params ?? {})}`),

	get: (id: string) => api.get<ChangeRequest>(`/change-requests/${id}`),

	create: (body: CRCreate, company_id: string) =>
		api.post<ChangeRequest>(`/change-requests?company_id=${company_id}`, body),

	deptApprove: (id: string, note?: string) =>
		api.post<ChangeRequest>(`/change-requests/${id}/dept-approve`, { note }),

	deptReject: (id: string, note?: string) =>
		api.post<ChangeRequest>(`/change-requests/${id}/dept-reject`, { note }),

	adminApprove: (id: string, company_id: string, note?: string) =>
		api.post<ChangeRequest>(`/change-requests/${id}/admin-approve?company_id=${company_id}`, { note }),

	adminReject: (id: string, note?: string) =>
		api.post<ChangeRequest>(`/change-requests/${id}/admin-reject`, { note }),
};
