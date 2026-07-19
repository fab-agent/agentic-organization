export const API_URL = import.meta.env.VITE_API_URL ?? '';
const BASE = API_URL;

function getToken(): string | null {
	if (typeof localStorage === 'undefined') return null;
	return localStorage.getItem('auth_token');
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const token = getToken();
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) headers['Authorization'] = `Bearer ${token}`;
	Object.assign(headers, init?.headers);

	const res = await fetch(`${BASE}${path}`, { headers, ...init });

	if (res.status === 401 && typeof window !== 'undefined') {
		localStorage.removeItem('auth_token');
		window.location.href = '/login';
		throw new Error('Oturum süresi doldu');
	}

	if (!res.ok) {
		const text = await res.text().catch(() => '');
		let msg = text;
		try { msg = JSON.parse(text)?.detail ?? text; } catch {}
		throw new Error(msg || `${res.status} ${res.statusText}`);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	get:    <T>(path: string)                => request<T>(path),
	post:   <T>(path: string, body: unknown) => request<T>(path, { method: 'POST',   body: JSON.stringify(body) }),
	put:    <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT',    body: JSON.stringify(body) }),
	patch:  <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH',  body: JSON.stringify(body) }),
	delete: (path: string)                   => request<void>(path, { method: 'DELETE' }),
};

export async function changePassword(password: string): Promise<void> {
	const res = await api.post<{ access_token: string }>('/auth/change-password', { password });
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem('auth_token', res.access_token);
	}
}

export async function invitePersonnel(
	personnelId: string,
	role: string,
	scopeId?: string,
): Promise<{ message: string; user_id: string }> {
	return api.post(`/personnel/${personnelId}/invite`, { role, scope_id: scopeId });
}
