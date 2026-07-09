import { api, changePassword as apiChangePassword } from '$lib/api/client';

export type UserCompany = {
	company_id: string;
	company_name: string;
	role: 'founder' | 'executive' | 'dept_head' | 'agent_owner' | 'user';
	scope_id: string | null;
	personnel_id: string | null;
};

export type AuthUser = {
	id: string;
	email: string;
	name: string;
	must_change_password: boolean;
	companies: UserCompany[];
};

// Role hierarchy weight — higher = more permissions
const ROLE_WEIGHT: Record<string, number> = {
	founder: 5,
	executive: 4,
	dept_head: 3,
	agent_owner: 2,
	user: 1,
};

let _user = $state<AuthUser | null>(null);
let _token = $state<string | null>(null);
let _loaded = $state(false);

function roleInCompany(companyId: string): UserCompany['role'] | null {
	return _user?.companies.find((c) => c.company_id === companyId)?.role ?? null;
}

export const authStore = {
	get user() { return _user; },
	get token() { return _token; },
	get loaded() { return _loaded; },
	get isLoggedIn() { return !!_user; },

	roleFor(companyId: string) {
		return roleInCompany(companyId);
	},

	/** Returns true if role weight >= required role weight for the given company. */
	can(companyId: string, minRole: UserCompany['role']): boolean {
		const role = roleInCompany(companyId);
		if (!role) return false;
		return (ROLE_WEIGHT[role] ?? 0) >= (ROLE_WEIGHT[minRole] ?? 0);
	},

	isFounder(companyId: string) {
		return roleInCompany(companyId) === 'founder';
	},

	/** Load token from localStorage and fetch /auth/me */
	async init() {
		const stored = localStorage.getItem('auth_token');
		if (!stored) { _loaded = true; return; }
		_token = stored;
		try {
			const me = await api.get<AuthUser>('/auth/me');
			_user = me;
		} catch {
			localStorage.removeItem('auth_token');
			_token = null;
		} finally {
			_loaded = true;
		}
	},

	async login(email: string, password: string): Promise<AuthUser> {
		const res = await api.post<{ access_token: string }>('/auth/token', { email, password });
		_token = res.access_token;
		localStorage.setItem('auth_token', _token);
		const me = await api.get<AuthUser>('/auth/me');
		_user = me;
		return me;
	},

	/** For first-login: user is already authenticated, just needs to set permanent password. */
	async changePassword(password: string): Promise<void> {
		await apiChangePassword(password);
		const me = await api.get<AuthUser>('/auth/me');
		_user = me;
	},

	logout() {
		_user = null;
		_token = null;
		localStorage.removeItem('auth_token');
	},
};
