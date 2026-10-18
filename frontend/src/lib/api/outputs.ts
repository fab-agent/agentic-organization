import { api, API_URL } from './client';

export type OutputFile = { path: string; size: number; sha256: string; mtime_ns: number };

/** The person's own workspace outputs (`out/`). No workspace yet is not an error. */
export const outputsApi = {
	async list(company_id?: string): Promise<{ id: string; files: OutputFile[] } | null> {
		let ws: { id: string };
		try {
			ws = await api.get<{ id: string }>(`/workspaces/me${company_id ? `?company_id=${company_id}` : ''}`);
		} catch {
			return null;
		}
		try {
			const r = await api.get<{ files: OutputFile[] }>(`/workspaces/${ws.id}/files`);
			return { id: ws.id, files: r.files };
		} catch {
			return { id: ws.id, files: [] };
		}
	},

	/** Saves as a download: never opened or executed by the app. */
	async download(workspaceId: string, path: string): Promise<void> {
		const token = localStorage.getItem('auth_token');
		const url = `${API_URL}/workspaces/${workspaceId}/files/${path.split('/').map(encodeURIComponent).join('/')}`;
		const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
		if (!res.ok) throw new Error(`İndirilemedi (${res.status})`);
		const blob = await res.blob();
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = path.split('/').pop() || 'dosya';
		a.rel = 'noopener';
		a.click();
		setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
	}
};

const RISKY = /\.(exe|bat|cmd|com|scr|js|vbs|ps1|msi|jar|docm|xlsm|pptm|app|sh)$/i;
/** Macro-enabled and script files are flagged before saving (ADR-0022 §8). */
export const isRisky = (path: string) => RISKY.test(path);
