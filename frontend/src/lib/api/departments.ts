import { api } from './client';

export type Department = {
	id: string;
	name: string;
	slug: string;
	description: string | null;
	goals: string | null;
	policies: string[];
	status: 'Active' | 'Inactive';
	created_at: string;
};

export type DepartmentCreate = Omit<Department, 'id' | 'created_at'>;
export type DepartmentUpdate = Partial<DepartmentCreate>;

export const departments = {
	list:   ()                                  => api.get<Department[]>('/departments'),
	get:    (id: string)                        => api.get<Department>(`/departments/${id}`),
	create: (body: DepartmentCreate)            => api.post<Department>('/departments', body),
	update: (id: string, body: DepartmentUpdate) => api.patch<Department>(`/departments/${id}`, body),
	delete: (id: string)                        => api.delete(`/departments/${id}`),
};
