import { api } from './client';

export interface CompanyStats {
	company_id: string;
	human_count: number;
	agent_count: number;
	total_personnel: number;
	active_agents: number;
	total_sessions: number;
	today_sessions: number;
	active_sessions: number;
	total_tokens: number;
	today_tokens: number;
	memory_count: number;
}

export interface MySession {
	id: string;
	title: string | null;
	status: 'active' | 'closed';
	updated_at: string;
	created_at: string;
}

export interface MyMemory {
	id: string;
	summary: string;
	session_id: string | null;
	created_at: string;
}

export interface MyDashboard {
	linked: boolean;
	personnel_id?: string;
	personnel_name?: string;
	personnel_title?: string | null;
	total_sessions?: number;
	today_sessions?: number;
	active_sessions?: number;
	total_tokens?: number;
	today_tokens?: number;
	recent_sessions?: MySession[];
	memories?: MyMemory[];
}

export const dashboardApi = {
	stats: (company_id?: string) => {
		const qs = company_id ? `?company_id=${company_id}` : '';
		return api.get<CompanyStats>(`/dashboard/stats${qs}`);
	},
	me: (company_id?: string) => {
		const qs = company_id ? `?company_id=${company_id}` : '';
		return api.get<MyDashboard>(`/dashboard/me${qs}`);
	},
};
