import { api } from './client';

export type Status = 'ok' | 'warn' | 'fail' | 'unknown';

type Section = { status: Status; reason?: string };

export type Usage = { requests: number; tokens_in: number; tokens_out: number };

export type Monitoring = {
	company_id: string;
	generated_at: string;
	status: Status;
	sections: {
		service: Section & { version: string; database: string };
		audit: Section & {
			events: number;
			anchor: 'ok' | 'truncated' | 'rewritten' | 'missing' | 'none_recorded';
			anchor_issues: number;
			verified: boolean | null;
			broken_at?: number | null;
		};
		gateway: Section & {
			day: Usage;
			month: Usage;
			top_agents_today: { persona_id: string; name: string | null; requests: number; tokens: number }[];
		};
		eval: Section & {
			days: number;
			runs: number;
			suspect_counts: Record<string, number>;
			truncated: number;
			invalid_events: number;
		};
		workspace: Section & {
			signer: 'ok' | 'unavailable';
			epoch?: number;
			crl_number?: number;
			signing_cert_days_left?: number;
			people_issued: number;
			last_issued: string | null;
		};
		clients: Section & {
			self_reported?: boolean;
			issued?: number;
			reporting?: number;
			behind?: number;
			never_reported?: number;
			silent?: number;
			not_reported_for_days?: number;
			drifting?: number;
			drifting_people?: {
				name: string | null;
				missing: number;
				modified: number;
				extra: number;
				unmanaged: number;
				interrupted: boolean;
			}[];
		};
	};
};

export const monitoringApi = {
	get: (companyId: string, deep = false) =>
		api.get<Monitoring>(`/admin/monitoring?company_id=${encodeURIComponent(companyId)}${deep ? '&deep=true' : ''}`)
};
