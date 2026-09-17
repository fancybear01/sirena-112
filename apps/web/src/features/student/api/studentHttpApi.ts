import { normalizeReport, normalizeScenario, normalizeSession } from '../../../api/adapters';
import type { ApiConfig } from '../../../api/config';
import { ApiError } from '../../../api/errors';
import { createHttpClient, type HttpClient } from '../../../api/httpClient';
import type { StudentApi, StudentAssignment, StudentOperatorCard, StudentSession } from './types';

function toStudentSession(value: unknown): StudentSession {
  const session = normalizeSession(value);
  if (session.state !== 'ACTIVE' && session.state !== 'SCORING' && session.state !== 'SCORED') {
    throw new ApiError('Назначенная сессия ещё не готова для обучающегося.', { code: 'INVALID_STATE' });
  }
  return {
    ...session,
    state: session.state,
    // Timestamps are not specified in Session yet; keep the timer usable with a local fallback.
    startedAt: session.startedAt ?? new Date().toISOString(),
    endedAt: session.endedAt ?? null,
  };
}

function normalizeAssignment(value: unknown): StudentAssignment {
  if (!value || typeof value !== 'object') {
    throw new ApiError('Core API вернул некорректное задание.', { code: 'INVALID_RESPONSE' });
  }
  const assignment = value as Record<string, unknown>;
  return {
    scenario: normalizeScenario(assignment.scenario),
    session: toStudentSession(assignment.session),
  };
}

export function createStudentHttpApi(
  config: Pick<ApiConfig, 'baseUrl'>,
  http: HttpClient = createHttpClient(config.baseUrl),
): StudentApi {
  return {
    async getAssignment() {
      const payload = await http.request<unknown>('/api/student/assignments');
      const assignments = Array.isArray(payload) ? payload : [payload];
      const current = assignments[0];
      if (!current) throw new ApiError('Активных заданий нет.', { status: 404, code: 'NO_ASSIGNMENT' });
      return normalizeAssignment(current);
    },

    async saveCard(sessionId, card) {
      return toStudentSession(await http.request(
        `/api/student/sessions/${encodeURIComponent(sessionId)}/card`,
        { method: 'PATCH', body: card },
      ));
    },

    async submitCard(sessionId, card: StudentOperatorCard) {
      return normalizeReport(await http.request(
        `/api/student/sessions/${encodeURIComponent(sessionId)}/submit`,
        { method: 'POST', body: card },
      ));
    },
  };
}
