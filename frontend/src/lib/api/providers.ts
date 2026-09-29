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

/** An OpenAI-compatible endpoint added by base URL + token (ADR-0016). */
export interface CustomEndpoint {
  provider: string;       // "custom:<slug>" — the value agents reference
  slug: string;
  display_name: string;
  base_url: string;
  status: 'active' | 'invalid';
  has_key: boolean;
  models: string[];
  last_tested: string | null;
}

export interface CustomEndpointCreate {
  name: string;
  base_url: string;
  api_key?: string;
  models?: string[];      // for servers without GET /models
}

export const providers = {
  status:    ()                          => api.get<ProviderStatus[]>('/providers/status'),
  models:    ()                          => api.get<ModelDef[]>('/providers/models'),
  setKey:    (provider: string, key: string, base_url?: string) =>
    api.post<ProviderStatus>(`/providers/${provider}/key`, { key, base_url }),
  deleteKey: (provider: string)          => api.delete(`/providers/${provider}/key`),
  test:      (provider: string)          =>
    api.post<ProviderStatus>(`/providers/${provider}/test`, {}),
  listCustom:   ()                              => api.get<CustomEndpoint[]>('/providers/custom'),
  saveCustom:   (body: CustomEndpointCreate)    => api.post<CustomEndpoint>('/providers/custom', body),
  testCustom:   (slug: string)                  => api.post<CustomEndpoint>(`/providers/custom/${slug}/test`, {}),
  deleteCustom: (slug: string)                  => api.delete(`/providers/custom/${slug}`),
};
