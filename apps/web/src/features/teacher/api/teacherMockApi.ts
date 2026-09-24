import { scenarioFixtures, scenarioStatusFixtures } from './scenarios.fixture';
import { ApiError } from '../../../api/errors';
import {
  getBrowserStorage,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from '../../../api/mockStorage';
import type { OperatorCard, SessionReport } from '../../../api/types';
import type {
  TeacherApi,
  TeacherScenario,
  TeacherServiceAssignment,
  TeacherSession,
} from './types';

type MockOptions = {
  scenarios?: TeacherScenario[];
  delayMs?: number;
  failScenarios?: boolean;
  serviceAssignments?: TeacherServiceAssignment[];
  storage?: Storage | null;
};

type StoredStudentSnapshot = {
  sessionId: string;
  endedAt: string | null;
  cardRevision: number;
  card: OperatorCard;
  report: SessionReport | null;
};

const storedSessionStates = new Set(['ACTIVE', 'COMPLETED', 'SCORING', 'SCORED', 'FAILED']);

function createEmptyCard(): TeacherSession['card'] {
  return {
    input: {
      caller: null,
      incident: null,
      address: null,
      description: null,
      victims: null,
      facts: {},
    },
    calculation: null,
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
    && typeof session.state === 'string'
    && storedSessionStates.has(session.state)
    && typeof session.startedAt === 'string'
    && (session.endedAt === null || typeof session.endedAt === 'string')
    && typeof session.cardRevision === 'number'
    && typeof session.timeLimitSeconds === 'number'
    && typeof session.timeLimitExceeded === 'boolean'
    && (session.report === null || typeof session.report === 'object')
    && Boolean(session.card && typeof session.card === 'object' && 'input' in session.card);
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

  function readStudentSnapshot(sessionId: string): StoredStudentSnapshot | null {
    if (!storage) return null;
    try {
      const raw = storage.getItem(studentDraftStorageKey);
      if (!raw) return null;
      const value = JSON.parse(raw) as Partial<StoredStudentSnapshot>;
      if (value.sessionId !== sessionId
        || (value.endedAt !== null && typeof value.endedAt !== 'string')
        || typeof value.cardRevision !== 'number'
        || !value.card || typeof value.card !== 'object'
        || !('input' in value.card)
        || (value.report !== null && typeof value.report !== 'object')) {
        return null;
      }
      return value as StoredStudentSnapshot;
    } catch {
      return null;
    }
  }

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
      if (currentSession) {
        const student = readStudentSnapshot(currentSession.id);
        if (student?.report) {
          persistSession({
            ...currentSession,
            state: 'SCORED',
            card: structuredClone(student.card),
            cardRevision: student.cardRevision,
            report: structuredClone(student.report),
            endedAt: student.endedAt,
          });
        }
      }
      return respond(currentSession);
    },

    async getServiceAssignments(sessionId) {
      if (!currentSession || currentSession.id !== sessionId) {
        throw new ApiError('Учебная сессия не найдена.', { status: 404 });
      }
      if (options.serviceAssignments) {
        return respond(options.serviceAssignments.map((item) => ({ ...item, sessionId })));
      }
      const student = readStudentSnapshot(sessionId);
      const services = student?.report ? student.card.calculation?.services ?? [] : [];
      const createdAt = student?.endedAt ?? new Date().toISOString();
      return respond(services.map((service, index): TeacherServiceAssignment => {
        const suffix = (index + 1).toString(16).padStart(12, '0');
        return {
          id: `10000000-0000-4000-8000-${suffix}`,
          sessionId,
          serviceId: service.id,
          displayName: service.displayName,
          cardRevision: student?.cardRevision ?? 0,
          status: 'ADDED',
          createdAt,
          updatedAt: createdAt,
          deadlineAt: new Date(Date.parse(createdAt) + 60 * 60 * 1000).toISOString(),
          overdue: false,
          history: [{
            eventId: `20000000-0000-4000-8000-${suffix}`,
            sequence: 1,
            fromStatus: null,
            status: 'ADDED',
            timestamp: createdAt,
            source: 'SYSTEM',
            comment: null,
            refusalReason: null,
          }],
        };
      }));
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
        cardRevision: 0,
        report: null,
        startedAt,
        endedAt: null,
        timeLimitSeconds: scenario.timeLimitSeconds ?? 30,
        timeLimitExceeded: false,
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
        timeLimitExceeded: Boolean(
          session.startedAt
          && Date.now() - Date.parse(session.startedAt) > session.timeLimitSeconds * 1000,
        ),
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
