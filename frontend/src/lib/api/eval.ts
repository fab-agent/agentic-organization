import { api } from './client';

export type Finding = {
	layer: 'model' | 'prompt' | 'tool' | 'policy';
	kind: string;
	severity: 'high' | 'medium' | 'low' | 'info';
	detail: string;
	evidence: [string, number] | null;
};

export type RunDiagnosis = {
	run_id: string;
	persona_id: string;
	suspect_layer: string | null;
	scores: Record<string, number>;
	findings: Finding[];
	events_seen: number;
	ignored_client_claims: number;
	invalid_events: number;
	truncated: boolean;
	updated_at: string;
	note: string;
};

export type Interval = { n: number; share: number | null; low: number | null; high: number | null };

export type EvalSummary = {
	runs: number;
	criteria: Record<string, { yes: number; no: number; unclear: number; success: Interval }>;
	suspect_counts: Record<string, number>;
	note: string;
};

export const evalApi = {
	runs: (personaId: string) => api.get<RunDiagnosis[]>(`/eval/personas/${personaId}/runs`),
	summary: (personaId: string) => api.get<EvalSummary>(`/eval/personas/${personaId}/summary`),
	diagnose: (personaId: string, runId: string) =>
		api.post<RunDiagnosis>(`/eval/personas/${personaId}/runs/${encodeURIComponent(runId)}/diagnose`, {})
};
