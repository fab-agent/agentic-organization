import { api } from './client.js';

export interface ProviderStatus {
  provider: string;
  display_name: string;
  status: 'active' | 'invalid' | 'unconfigured';
  has_key: boolean;
  models: Array<{ id: string; name: string }>;
  last_tested: string | null;
}

export type PriceTier = 'low' | 'medium' | 'high' | 'premium';

export interface ModelDef {
  id: string;
  name: string;
  provider: string;
  tier: PriceTier;
  input_per_m: number | null;   // USD per 1M input tokens
  output_per_m: number | null;  // USD per 1M output tokens
}

export const providers = {
  status:    ()                          => api.get<ProviderStatus[]>('/providers/status'),
  models:    ()                          => api.get<ModelDef[]>('/providers/models'),
  setKey:    (provider: string, key: string) =>
    api.post<ProviderStatus>(`/providers/${provider}/key`, { key }),
  deleteKey: (provider: string)          => api.delete(`/providers/${provider}/key`),
  test:      (provider: string)          =>
    api.post<ProviderStatus>(`/providers/${provider}/test`, {}),
};
