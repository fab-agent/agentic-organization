import { api } from './client.js';

export interface TelegramConfigResponse {
	configured: boolean;
	admin_chat_id?: string;
	is_active?: boolean;
	bot_username?: string;
	bot_name?: string;
}

export const telegram = {
	getConfig: () => api.get<TelegramConfigResponse>('/telegram/config'),

	saveConfig: (bot_token: string, admin_chat_id: string) =>
		api.put<TelegramConfigResponse>('/telegram/config', { bot_token, admin_chat_id }),

	test: () => api.post<{ sent: boolean }>('/telegram/test', {}),

	deleteConfig: () => api.delete('/telegram/config'),
};
