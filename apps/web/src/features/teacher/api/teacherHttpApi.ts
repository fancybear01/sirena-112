import { normalizeScenario, normalizeServiceAssignments, normalizeSession } from '../../../api/adapters';
import type { ApiConfig } from '../../../api/config';
import { createHttpClient, type HttpClient } from '../../../api/httpClient';
import { ApiError } from '../../../api/errors';
import { apiTeacherSessionStorageKey, getBrowserStorage } from '../../../api/mockStorage';
import type { TeacherApi, TeacherScenario, TeacherSession } from './types';

function toTeacherSession(value: unknown, fallbackStartedAt?: string | null): TeacherSession {
  const session = normalizeSession(value);
  return {
    ...session,
    startedAt: session.startedAt ?? fallbackStartedAt ?? null,
    endedAt: session.endedAt ?? null,
  };
}

export function createTeacherHttpApi(
  config: Pick<ApiConfig, 'baseUrl'>,
  http: HttpClient = createHttpClient(config.baseUrl),
  storage: Storage | null = getBrowserStorage(),
): TeacherApi {
  function readCachedSession(): TeacherSession | null {
    if (!storage) return null;
    try {
      const raw = storage.getItem(apiTeacherSessionStorageKey);
      return raw ? toTeacherSession(JSON.parse(raw)) : null;
    } catch {
      storage.removeItem(apiTeacherSessionStorageKey);
      return null;
    }
  }

  function cacheSession(session: TeacherSession | null) {
    if (!storage) return;
    if (session) storage.setItem(apiTeacherSessionStorageKey, JSON.stringify(session));
    else storage.removeItem(apiTeacherSessionStorageKey);
  }

  return {
    async getAnalytics() {
      return http.request('/api/teacher/analytics/summary');
    },

    async getStudents() {
      return http.request<{ id: string; displayName: string; username: string }[]>('/api/teacher/students');
    },
    async getScenarios() {
      const payload = await http.request<unknown[]>('/api/teacher/scenarios');
      if (!Array.isArray(payload)) return [];
      return payload.map((item): TeacherScenario => ({
        ...normalizeScenario(item),
        // Scenario readiness is absent from OpenAPI, so contract scenarios are launchable by default.
        status: 'READY',
      }));
    },

    async getCurrentSession() {
      const cached = readCachedSession();
      if (!cached) return null;
      try {
        const current = toTeacherSession(await http.request(
          `/api/teacher/sessions/${encodeURIComponent(cached.id)}`,
        ));
        cacheSession(current);
        return current;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          cacheSession(null);
          return null;
        }
        throw error;
      }
    },

    async getServiceAssignments(sessionId) {
      return normalizeServiceAssignments(await http.request(
        `/api/teacher/sessions/${encodeURIComponent(sessionId)}/service-assignments`,
      ));
    },

    async launchSession(scenarioId, studentId) {
      const created = normalizeSession(await http.request('/api/teacher/sessions', {
        method: 'POST',
        body: { scenarioId, ...(studentId ? { studentId } : {}) },
      }));
      const startedAt = created.startedAt ?? new Date().toISOString();
      const started = toTeacherSession(await http.request(
        `/api/teacher/sessions/${encodeURIComponent(created.id)}/start`,
        { method: 'POST' },
      ), startedAt);
      cacheSession(started);
      return started;
    },

    async stopSession(sessionId) {
      const cached = readCachedSession();
      const stopped = toTeacherSession(await http.request(
        `/api/teacher/sessions/${encodeURIComponent(sessionId)}/stop`,
        { method: 'POST' },
      ), cached?.startedAt);
      cacheSession(stopped);
      return stopped;
    },

    async clearSession() {
      cacheSession(null);
    },
  };
}
