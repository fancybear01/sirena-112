export type ApiMode = 'mock' | 'api';

type ApiEnvironment = {
  VITE_API_MODE?: string;
  VITE_API_BASE_URL?: string;
};

export type ApiConfig = {
  mode: ApiMode;
  baseUrl: string;
};

const defaultBaseUrl = 'http://localhost:8080';

export function resolveApiConfig(env: ApiEnvironment): ApiConfig {
  const rawMode = env.VITE_API_MODE?.trim().toLowerCase();
  const mode: ApiMode = rawMode === 'api' ? 'api' : 'mock';
  const baseUrl = (env.VITE_API_BASE_URL?.trim() || defaultBaseUrl).replace(/\/+$/, '');
  return { mode, baseUrl };
}

export const apiConfig = resolveApiConfig({
  VITE_API_MODE: import.meta.env.VITE_API_MODE,
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
});
