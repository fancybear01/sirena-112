import { normalizeReport, normalizeScenario, normalizeSession } from '../../../api/adapters';
import type { ApiConfig } from '../../../api/config';
import { ApiError } from '../../../api/errors';
import { createHttpClient, type HttpClient } from '../../../api/httpClient';
import { apiTeacherSessionStorageKey, getBrowserStorage } from '../../../api/mockStorage';
import type {
  StudentApi,
  StudentAssignment,
  StudentCardForm,
  StudentCardInput,
  StudentSession,
} from './types';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function normalizeCardForm(value: unknown): StudentCardForm {
  if (!isRecord(value) || typeof value.classifierVersion !== 'string'
    || !Array.isArray(value.signGroups) || !Array.isArray(value.questions)) {
    throw new ApiError('Core API вернул некорректную форму карточки.', { code: 'INVALID_RESPONSE' });
  }
  const signGroups: StudentCardForm['signGroups'] = value.signGroups.map((group) => {
    if (!isRecord(group) || typeof group.id !== 'string' || typeof group.label !== 'string'
      || (group.level !== 1 && group.level !== 2 && group.level !== 3) || !Array.isArray(group.options)) {
      throw new ApiError('Core API вернул некорректную группу признаков.', { code: 'INVALID_RESPONSE' });
    }
    return {
      id: group.id,
      label: group.label,
      level: group.level as 1 | 2 | 3,
      required: group.required === true,
      options: group.options.flatMap((option) => (
        isRecord(option) && typeof option.id === 'string' && typeof option.label === 'string'
          ? [{ id: option.id, label: option.label }]
          : []
      )),
    };
  });
  const questions: StudentCardForm['questions'] = value.questions.map((question) => {
    if (!isRecord(question) || typeof question.id !== 'string' || typeof question.label !== 'string'
      || (question.inputType !== 'SINGLE_SELECT'
        && question.inputType !== 'MULTI_SELECT'
        && question.inputType !== 'TEXT')) {
      throw new ApiError('Core API вернул некорректный дополнительный вопрос.', { code: 'INVALID_RESPONSE' });
    }
    return {
      id: question.id,
      label: question.label,
      inputType: question.inputType as 'SINGLE_SELECT' | 'MULTI_SELECT' | 'TEXT',
      required: question.required === true,
      options: Array.isArray(question.options)
        ? question.options.flatMap((option) => (
            isRecord(option) && typeof option.id === 'string' && typeof option.label === 'string'
              ? [{ id: option.id, label: option.label }]
              : []
          ))
        : [],
    };
  });
  return { classifierVersion: value.classifierVersion, signGroups, questions };
}

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
  storage: Storage | null = getBrowserStorage(),
): StudentApi {
  async function getCachedAssignment(): Promise<StudentAssignment | null> {
    if (!storage) return null;
    let cached: Record<string, unknown>;
    try {
      const raw = storage.getItem(apiTeacherSessionStorageKey);
      if (!raw) return null;
      const value: unknown = JSON.parse(raw);
      if (!isRecord(value) || typeof value.id !== 'string' || typeof value.scenarioId !== 'string') return null;
      cached = value;
    } catch {
      return null;
    }
    const [sessionPayload, scenariosPayload] = await Promise.all([
      http.request<unknown>(`/api/student/sessions/${encodeURIComponent(String(cached.id))}`),
      http.request<unknown>('/api/teacher/scenarios'),
    ]);
    const scenarios = Array.isArray(scenariosPayload) ? scenariosPayload : [];
    const scenario = scenarios.find((item) => isRecord(item) && item.id === cached.scenarioId);
    if (!scenario) throw new ApiError('Сценарий активной сессии не найден.', { status: 404 });
    return { scenario: normalizeScenario(scenario), session: toStudentSession(sessionPayload) };
  }

  return {
    async getAssignment() {
      try {
        const payload = await http.request<unknown>('/api/student/assignments');
        const assignments = Array.isArray(payload) ? payload : [payload];
        const current = assignments[0];
        if (!current) throw new ApiError('Активных заданий нет.', { status: 404, code: 'NO_ASSIGNMENT' });
        return normalizeAssignment(current);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        const cached = await getCachedAssignment();
        if (cached) return cached;
        throw error;
      }
    },

    async getCardForm(sessionId) {
      return normalizeCardForm(await http.request(
        `/api/student/sessions/${encodeURIComponent(sessionId)}/card-form`,
      ));
    },

    async saveCard(sessionId, input, expectedRevision) {
      return toStudentSession(await http.request(
        `/api/student/sessions/${encodeURIComponent(sessionId)}/card`,
        { method: 'PATCH', body: { input, expectedRevision } },
      ));
    },

    async submitCard(sessionId, input: StudentCardInput, expectedRevision) {
      return normalizeReport(await http.request(
        `/api/student/sessions/${encodeURIComponent(sessionId)}/submit`,
        { method: 'POST', body: { input, expectedRevision } },
      ));
    },
  };
}
