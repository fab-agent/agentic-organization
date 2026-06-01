const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		headers: { 'Content-Type': 'application/json', ...init?.headers },
		...init,
	});
	if (!res.ok) {
		const text = await res.text().catch(() => '');
		throw new Error(`${res.status} ${res.statusText}: ${text}`);
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	get:    <T>(path: string)                      => request<T>(path),
	post:   <T>(path: string, body: unknown)       => request<T>(path, { method: 'POST',   body: JSON.stringify(body) }),
	patch:  <T>(path: string, body: unknown)       => request<T>(path, { method: 'PATCH',  body: JSON.stringify(body) }),
	delete: (path: string)                         => request<void>(path, { method: 'DELETE' }),
};
