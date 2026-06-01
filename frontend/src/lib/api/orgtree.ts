import { api } from './client';
import type { OrgNode } from '$lib/types/org';

export const orgTree = {
	get: () => api.get<OrgNode[]>('/org-tree'),
};
