import { api } from './client';

export type AssistantContext = {
	me: { name: string; title: string | null; department: string | null; roles: string[] };
	agent: { id: string; name: string; status: string } | null;
	tools: { name: string; description: string | null }[];
	team: {
		department: string | null;
		manager: { name: string; role: string | null } | null;
		colleagues: { name: string; role: string | null }[];
	};
	policies: { name: string; content: string }[];
	learned: { kind: string; level: string; version: number; text: string }[];
	company: {
		name: string | null;
		mission: string | null;
		vision: string | null;
		goals: string[] | string | null;
		department_goals: string | null;
	};
};

export const assistantApi = {
	context: (company_id?: string) =>
		api.get<AssistantContext>(`/assistant/context${company_id ? `?company_id=${company_id}` : ''}`)
};
