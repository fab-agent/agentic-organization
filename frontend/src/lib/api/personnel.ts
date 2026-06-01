import { api } from './client';

export type AgentSkill = {
	id: string;
	name: string;
	version: string;
	description: string | null;
};

export type AgentConfig = {
	id: string;
	model: string;
	model_version: string | null;
	status: 'active' | 'draft' | 'inactive';
	responsible_id: string | null;
	responsible_name: string | null;
	skills: AgentSkill[];
};

export type PersonnelItem = {
	id: string;
	name: string;
	slug: string;
	title: string | null;
	role: string | null;
	type: 'human' | 'agent';
	department_id: string | null;
	department_name: string | null;
	manager_id: string | null;
	manager_name: string | null;
	agent_config?: AgentConfig;
	created_at: string;
};

export type PersonnelCreate = {
	name: string;
	slug: string;
	title?: string;
	role?: string;
	type?: 'human' | 'agent';
	department_id?: string;
	manager_id?: string;
};

export type PersonnelUpdate = Partial<PersonnelCreate>;

export const personnel = {
	list:   (params?: { department_id?: string; type?: string }) => {
		const qs = new URLSearchParams();
		if (params?.department_id) qs.set('department_id', params.department_id);
		if (params?.type)          qs.set('type', params.type);
		const query = qs.toString() ? `?${qs}` : '';
		return api.get<PersonnelItem[]>(`/personnel${query}`);
	},
	get:    (id: string)                          => api.get<PersonnelItem>(`/personnel/${id}`),
	create: (body: PersonnelCreate)               => api.post<PersonnelItem>('/personnel', body),
	update: (id: string, body: PersonnelUpdate)   => api.patch<PersonnelItem>(`/personnel/${id}`, body),
	delete: (id: string)                          => api.delete(`/personnel/${id}`),

	getAgentConfig:    (id: string)                        => api.get<AgentConfig>(`/personnel/${id}/agent-config`),
	createAgentConfig: (id: string, body: Partial<AgentConfig>) => api.post<AgentConfig>(`/personnel/${id}/agent-config`, body),
	updateAgentConfig: (id: string, body: Partial<AgentConfig>) => api.patch<AgentConfig>(`/personnel/${id}/agent-config`, body),

	listSkills: (id: string)                        => api.get<AgentSkill[]>(`/personnel/${id}/skills`),
	addSkill:   (id: string, body: Omit<AgentSkill, 'id'>) => api.post<AgentSkill>(`/personnel/${id}/skills`, body),
	deleteSkill:(id: string, skillId: string)       => api.delete(`/personnel/${id}/skills/${skillId}`),
};
