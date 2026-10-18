import { api } from './client.js';

export interface TelegramConfigResponse {
	configured: boolean;
	admin_chat_id?: string;
	is_active?: boolean;
	bot_username?: string;
	bot_name?: string;
}

const q = (company_id?: string) => (company_id ? `?company_id=${company_id}` : '');

export const telegram = {
	getConfig: (company_id?: string) =>
		api.get<TelegramConfigResponse>(`/telegram/config${q(company_id)}`),

	saveConfig: (bot_token: string, admin_chat_id: string, company_id?: string) =>
		api.put<TelegramConfigResponse>(`/telegram/config${q(company_id)}`, { bot_token, admin_chat_id }),

	test: (company_id?: string) => api.post<{ sent: boolean }>(`/telegram/test${q(company_id)}`, {}),

	deleteConfig: (company_id?: string) => api.delete(`/telegram/config${q(company_id)}`),
};
