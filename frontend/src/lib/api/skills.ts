import { api } from './client';

export interface CompanySkill {
	id: string;
	company_id: string;
	name: string;
	slug: string;
	description: string | null;
	content: string | null;
	skill_type: 'builtin' | 'mcp' | 'http' | 'function' | 'database';
	config_json: string | null;
	is_active: boolean;
	assigned_agents: string[];
	created_at: string;
	updated_at: string;
}

export interface SkillCreate {
	company_id: string;
	name: string;
	slug: string;
	description?: string;
	content?: string;
	skill_type?: string;
	config_json?: string;
}

export interface SkillUpdate {
	name?: string;
	slug?: string;
	description?: string;
	content?: string;
	skill_type?: string;
	config_json?: string;
	is_active?: boolean;
}

export interface BuiltinTool {
	value: string;
	label_tr: string;
	label_en: string;
	description_tr: string;
	description_en: string;
	icon: string;
}

export const skillsApi = {
	list: (company_id?: string) => {
		const qs = company_id ? `?company_id=${company_id}` : '';
		return api.get<CompanySkill[]>(`/company-skills${qs}`);
	},
	get: (id: string) => api.get<CompanySkill>(`/company-skills/${id}`),
	create: (body: SkillCreate) => api.post<CompanySkill>('/company-skills', body),
	update: (id: string, body: SkillUpdate, propose = false, personnel_id?: string) => {
		const qs = new URLSearchParams();
		if (propose) qs.set('propose', 'true');
		if (personnel_id) qs.set('personnel_id', personnel_id);
		const q = qs.toString() ? `?${qs}` : '';
		return api.put<CompanySkill | { change_request_id: string; status: string }>(
			`/company-skills/${id}${q}`, body
		);
	},
	delete: (id: string) => api.delete(`/company-skills/${id}`),
	assign: (skill_id: string, agent_config_id: string) =>
		api.post(`/company-skills/${skill_id}/assign/${agent_config_id}`, {}),
	unassign: (skill_id: string, agent_config_id: string) =>
		api.delete(`/company-skills/${skill_id}/assign/${agent_config_id}`),
	listBuiltinTools: () => api.get<BuiltinTool[]>('/builtin-tools'),
};
