import { apiConfig } from './config';
import { createHttpClient } from './httpClient';

export type AuthRole = 'ADMIN' | 'TEACHER' | 'STUDENT';
export type CurrentUser = { id: string; username: string; displayName: string; role: AuthRole; groupId: string | null };

const http = createHttpClient(apiConfig.baseUrl);

export const secureAuth = import.meta.env.VITE_AUTH_MODE === 'secure';
export const authApi = {
  me: () => http.request<CurrentUser>('/api/auth/me'),
  login: (username: string, password: string) => http.request<CurrentUser>('/api/auth/login', {
    method: 'POST', body: { username, password },
  }),
  logout: () => http.request<void>('/api/auth/logout', { method: 'POST' }),
};

export function pathForRole(role: AuthRole): string {
  return role === 'ADMIN' ? '/admin' : role === 'TEACHER' ? '/teacher' : '/student';
}
