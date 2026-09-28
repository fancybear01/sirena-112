import { apiConfig } from './config';
import { createHttpClient } from './httpClient';
import {
  apiTeacherSessionStorageKey,
  getBrowserStorage,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from './mockStorage';

export type AuthRole = 'ADMIN' | 'TEACHER' | 'STUDENT';
export type CurrentUser = { id: string; username: string; displayName: string; role: AuthRole; groupId: string | null };

const http = createHttpClient(apiConfig.baseUrl);

export const authApi = {
  me: () => http.request<CurrentUser>('/api/auth/me'),
  login: (username: string, password: string) => http.request<CurrentUser>('/api/auth/login', {
    method: 'POST', body: { username, password },
  }),
  logout: () => http.request<void>('/api/auth/logout', { method: 'POST' }),
};

export function clearPrivateBrowserState() {
  const storage = getBrowserStorage();
  if (!storage) return;
  [apiTeacherSessionStorageKey, teacherSessionStorageKey, studentDraftStorageKey]
    .forEach((key) => storage.removeItem(key));
}

export function pathForRole(role: AuthRole): string {
  return role === 'ADMIN' ? '/admin' : role === 'TEACHER' ? '/teacher' : '/student';
}
