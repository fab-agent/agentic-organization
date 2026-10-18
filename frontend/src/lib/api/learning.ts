import { api } from './client';

export type SignalKind = 'thumbs_up' | 'thumbs_down' | 'correction';

export const learningApi = {
	give: (message_id: string, kind: SignalKind, note?: string) =>
		api.post<{ id: string }>('/learning/signals', { message_id, kind, note }),
	withdraw: (message_id: string, kind: SignalKind) =>
		api.delete(`/learning/signals/${message_id}/${kind}`)
};
