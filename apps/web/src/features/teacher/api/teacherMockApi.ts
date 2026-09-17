import { scenarioFixtures, scenarioStatusFixtures } from './scenarios.fixture';
import { ApiError } from '../../../api/errors';
import {
  getBrowserStorage,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from '../../../api/mockStorage';
import type { TeacherApi, TeacherScenario, TeacherSession } from './types';

type MockOptions = {
  scenarios?: TeacherScenario[];
  delayMs?: number;
  failScenarios?: boolean;
  storage?: Storage | null;
};

function createEmptyCard(): TeacherSession['card'] {
  return {
    incidentType: null,
    signs: null,
    address: null,
    requiredServices: [],
    facts: {},
  };
}

function makeUuid() {
  return crypto.randomUUID();
}

function isStoredSession(value: unknown): value is TeacherSession {
  if (!value || typeof value !== 'object') return false;
  const session = value as Partial<TeacherSession>;
  return typeof session.id === 'string'
    && typeof session.scenarioId === 'string'
    && session.mode === 'CARD'
    && (session.state === 'ACTIVE' || session.state === 'COMPLETED')
    && typeof session.startedAt === 'string'
    && (session.endedAt === null || typeof session.endedAt === 'string')
    && session.report === null
    && Boolean(session.card && typeof session.card === 'object');
}

export function createTeacherMockApi(options: MockOptions = {}): TeacherApi {
  const scenarios = options.scenarios ?? scenarioFixtures.map((scenario): TeacherScenario => ({
    ...scenario,
    status: scenarioStatusFixtures[scenario.id] ?? 'READY',
  }));
  const delayMs = options.delayMs ?? 250;
  const storage = options.storage === undefined ? getBrowserStorage() : options.storage;

  function readSession(): TeacherSession | null {
    if (!storage) return null;
    try {
      const raw = storage.getItem(teacherSessionStorageKey);
      if (!raw) return null;
      const parsed: unknown = JSON.parse(raw);
      if (isStoredSession(parsed)) return parsed;
      storage.removeItem(teacherSessionStorageKey);
    } catch {
      // Corrupted or unavailable mock storage behaves like an empty backend.
    }
    return null;
  }

  let currentSession = readSession();

  function persistSession(session: TeacherSession | null) {
    currentSession = session;
    if (!storage) return;
    try {
      if (session) {
        storage.setItem(teacherSessionStorageKey, JSON.stringify(session));
      } else {
        storage.removeItem(teacherSessionStorageKey);
      }
    } catch {
      // The flow still works in memory when browser storage is unavailable.
    }
  }

  async function respond<T>(value: T): Promise<T> {
    if (delayMs > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    }
    return structuredClone(value);
  }

  return {
    async getScenarios() {
      if (options.failScenarios) {
        await respond(null);
        throw new ApiError('Проверьте соединение и повторите попытку.');
      }
      return respond(scenarios);
    },

    async getCurrentSession() {
      return respond(currentSession);
    },

    async launchSession(scenarioId) {
      const scenario = scenarios.find((item) => item.id === scenarioId);
      if (!scenario || scenario.status !== 'READY') {
        throw new ApiError('Сценарий не готов к запуску.', { status: 409 });
      }

      const startedAt = new Date().toISOString();
      const session: TeacherSession = {
        id: makeUuid(),
        scenarioId,
        mode: 'CARD',
        state: 'ACTIVE',
        card: createEmptyCard(),
        report: null,
        startedAt,
        endedAt: null,
      };
      try {
        storage?.removeItem(studentDraftStorageKey);
      } catch {
        // A blocked storage must not prevent launching an in-memory mock session.
      }
      persistSession(session);
      return respond(session);
    },

    async stopSession(sessionId) {
      const session = currentSession;
      if (!session || session.id !== sessionId || session.state !== 'ACTIVE') {
        throw new ApiError('Активная сессия не найдена.', { status: 404 });
      }

      const completed: TeacherSession = {
        ...session,
        state: 'COMPLETED',
        endedAt: new Date().toISOString(),
      };
      persistSession(completed);
      return respond(completed);
    },

    async clearSession() {
      await respond(null);
      persistSession(null);
    },
  };
}

export const teacherMockApi = createTeacherMockApi();
