import { api } from './client';

export type Department = {
	id: string;
	name: string;
	slug: string;
	parent_id: string | null;
	parent_name: string | null;
	description: string | null;
	goals: string | null;
	policies: string[];      // policy names (for display)
	policy_ids: string[];    // policy IDs (for selection UI)
	status: 'Active' | 'Inactive';
	created_at: string;
	children?: Department[];
};

export type DepartmentCreate = {
	name: string;
	slug: string;
	parent_id?: string | null;
	description?: string | null;
	goals?: string | null;
	status?: 'Active' | 'Inactive';
};
export type DepartmentUpdate = Partial<DepartmentCreate>;

export const departments = {
	list:        (company_id?: string) => api.get<Department[]>(company_id ? `/departments?company_id=${company_id}` : '/departments'),
	get:         (id: string) => api.get<Department>(`/departments/${id}`),
	create:      (body: DepartmentCreate, company_id?: string) => api.post<Department>(company_id ? `/departments?company_id=${company_id}` : '/departments', body),
	update:      (id: string, body: DepartmentUpdate) => api.patch<Department>(`/departments/${id}`, body),
	delete:      (id: string) => api.delete(`/departments/${id}`),
	tree:        (company_id?: string) => api.get<Department[]>(company_id ? `/departments/tree/root?company_id=${company_id}` : '/departments/tree/root'),
	setPolicies: (id: string, policy_ids: string[]) => api.put<Department>(`/departments/${id}/policies`, { policy_ids }),
};
