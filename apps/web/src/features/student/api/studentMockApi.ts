import { assignedScenarioFixture } from './student.fixture';
import { ApiError } from '../../../api/errors';
import {
  getBrowserStorage,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from '../../../api/mockStorage';
import type { Session } from '../../../api/types';
import { scenarioFixtures } from '../../teacher/api/scenarios.fixture';
import type {
  ScoreCriterion,
  StudentApi,
  StudentAssignment,
  StudentOperatorCard,
  StudentSession,
  StudentSessionReport,
} from './types';

type MockOptions = {
  delayMs?: number;
  failLoad?: boolean;
  failSave?: boolean;
  failSubmit?: boolean;
  storage?: Storage | null;
};

type StoredStudentState = {
  sessionId: string;
  scenarioId: string;
  startedAt: string;
  endedAt: string | null;
  card: StudentOperatorCard;
  report: StudentSessionReport | null;
};

const fallbackSessionId = 'a13e08ea-220f-458a-95f6-95b7c3a3f14c';

export function createEmptyStudentCard(): StudentOperatorCard {
  return {
    incidentType: null,
    signs: null,
    address: null,
    requiredServices: [],
    facts: { description: '' },
  };
}

function isStoredState(value: unknown): value is StoredStudentState {
  if (!value || typeof value !== 'object') return false;
  const state = value as Partial<StoredStudentState>;
  return typeof state.sessionId === 'string'
    && typeof state.scenarioId === 'string'
    && typeof state.startedAt === 'string'
    && (state.endedAt === null || typeof state.endedAt === 'string')
    && Boolean(state.card && typeof state.card === 'object')
    && (state.report === null || Boolean(state.report && typeof state.report === 'object'));
}

function scoreCard(card: StudentOperatorCard, sessionId: string): StudentSessionReport {
  const description = String(card.facts.description ?? '').trim().toLocaleLowerCase('ru-RU');
  const normalizedAddress = (card.address ?? '').trim().toLocaleLowerCase('ru-RU');
  const hasService = (service: string) => card.requiredServices.includes(service);
  const hasDescriptionDetails = description.length >= 30
    && /(дым|задым|пожар|огонь)/.test(description)
    && /(люд|человек|пят)/.test(description);

  const criteria: ScoreCriterion[] = [
    {
      code: 'INCIDENT_TYPE',
      passed: card.incidentType === 'FIRE',
      points: card.incidentType === 'FIRE' ? 25 : 0,
      maxPoints: 25,
      message: card.incidentType === 'FIRE'
        ? 'Тип «Пожар» определён верно.'
        : 'По условиям сценария итоговый тип должен быть «Пожар».',
    },
    {
      code: 'ADDRESS',
      passed: normalizedAddress.includes('лесн') && normalizedAddress.includes('14'),
      points: normalizedAddress.includes('лесн') && normalizedAddress.includes('14') ? 20 : 8,
      maxPoints: 20,
      message: normalizedAddress.includes('лесн') && normalizedAddress.includes('14')
        ? 'Адрес происшествия зафиксирован полностью.'
        : 'Адрес указан, но не совпадает с адресом из сообщения: ул. Лесная, д. 14.',
    },
    {
      code: 'DESCRIPTION',
      passed: hasDescriptionDetails,
      points: hasDescriptionDetails ? 20 : 10,
      maxPoints: 20,
      message: hasDescriptionDetails
        ? 'В описании отражены характер угрозы и сведения о людях.'
        : 'Добавьте в описание задымление и информацию о людях на пятом этаже.',
    },
    {
      code: 'SERVICES',
      passed: hasService('FIRE') && hasService('AMBULANCE'),
      points: hasService('FIRE') && hasService('AMBULANCE') ? 25 : 10,
      maxPoints: 25,
      message: hasService('FIRE') && hasService('AMBULANCE')
        ? 'Пожарная охрана и скорая помощь выбраны обоснованно.'
        : 'Для этого сценария нужны пожарная охрана и скорая помощь.',
    },
    {
      code: 'COMPLETENESS',
      passed: true,
      points: 10,
      maxPoints: 10,
      message: 'Все обязательные поля карточки заполнены.',
    },
  ];

  const errors = criteria
    .filter((criterion) => !criterion.passed)
    .map((criterion) => ({
      code: criterion.code,
      message: criterion.message,
      field: ({
        INCIDENT_TYPE: 'incidentType',
        ADDRESS: 'address',
        DESCRIPTION: 'facts.description',
        SERVICES: 'requiredServices',
      } as Record<string, string>)[criterion.code] ?? null,
    }));
  const score = criteria.reduce((total, criterion) => total + criterion.points, 0);
  const recommendations = errors.length === 0
    ? ['Сохраняйте тот же порядок: классификация, адрес, обстоятельства, список служб.']
    : errors.map((error) => ({
      INCIDENT_TYPE: 'Сопоставляйте итоговый тип с ключевыми признаками из сообщения.',
      ADDRESS: 'Перепроверяйте улицу и номер дома перед отправкой карточки.',
      DESCRIPTION: 'Фиксируйте источник опасности, этаж и наличие людей.',
      SERVICES: 'Формируйте список служб с учётом возможных пострадавших.',
    } as Record<string, string>)[error.code]).filter(Boolean);

  return {
    sessionId,
    score,
    maxScore: 100,
    passed: score >= 70,
    criteria,
    errors,
    recommendations,
  };
}

export function createStudentMockApi(options: MockOptions = {}): StudentApi {
  const storage = options.storage === undefined ? getBrowserStorage() : options.storage;
  const delayMs = options.delayMs ?? 350;

  function readTeacherSession(): Session | null {
    if (!storage) return null;
    try {
      const raw = storage.getItem(teacherSessionStorageKey);
      if (!raw) return null;
      const value = JSON.parse(raw) as Partial<Session>;
      return typeof value.id === 'string' && typeof value.scenarioId === 'string'
        && value.state === 'ACTIVE' ? value as Session : null;
    } catch {
      return null;
    }
  }

  function readState(sessionId: string, scenarioId: string, startedAt: string): StoredStudentState {
    if (storage) {
      try {
        const raw = storage.getItem(studentDraftStorageKey);
        if (raw) {
          const parsed: unknown = JSON.parse(raw);
          if (isStoredState(parsed) && parsed.sessionId === sessionId) return parsed;
          storage.removeItem(studentDraftStorageKey);
        }
      } catch {
        // Unavailable or corrupted storage falls back to an empty in-memory assignment.
      }
    }
    return {
      sessionId,
      scenarioId,
      startedAt,
      endedAt: null,
      card: createEmptyStudentCard(),
      report: null,
    };
  }

  let state: StoredStudentState | null = null;

  function getContext() {
    const teacherSession = readTeacherSession();
    const sessionId = teacherSession?.id ?? fallbackSessionId;
    const scenarioId = teacherSession?.scenarioId ?? assignedScenarioFixture.id;
    const startedAt = teacherSession?.startedAt || new Date().toISOString();
    const scenario = scenarioId === assignedScenarioFixture.id
      ? assignedScenarioFixture
      : scenarioFixtures.find((item) => item.id === scenarioId) ?? assignedScenarioFixture;
    if (!state || state.sessionId !== sessionId) {
      state = readState(sessionId, scenarioId, startedAt);
    }
    return { scenario, state };
  }

  function persist(next: StoredStudentState) {
    state = structuredClone(next);
    if (!storage) return;
    try {
      storage.setItem(studentDraftStorageKey, JSON.stringify(state));
    } catch {
      // The demonstration remains usable in memory when localStorage is unavailable.
    }
  }

  function makeSession(current: StoredStudentState): StudentSession {
    return {
      id: current.sessionId,
      scenarioId: current.scenarioId,
      mode: 'CARD',
      state: current.report ? 'SCORED' : 'ACTIVE',
      card: structuredClone(current.card),
      report: structuredClone(current.report),
      startedAt: current.startedAt,
      endedAt: current.endedAt,
    };
  }

  async function respond<T>(value: T): Promise<T> {
    if (delayMs > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    }
    return structuredClone(value);
  }

  return {
    async getAssignment(): Promise<StudentAssignment> {
      if (options.failLoad) {
        await respond(null);
        throw new ApiError('Повторите попытку — сохранённый черновик останется на этом устройстве.');
      }
      const current = getContext();
      return respond({ scenario: current.scenario, session: makeSession(current.state) });
    },

    async saveCard(requestSessionId, card) {
      const current = getContext().state;
      if (requestSessionId !== current.sessionId || current.report) {
        throw new ApiError('Активная сессия не найдена.', { status: 404 });
      }
      if (options.failSave) {
        await respond(null);
        throw new ApiError('Не удалось сохранить черновик.');
      }
      persist({ ...current, card, report: null });
      return respond(makeSession(state!));
    },

    async submitCard(requestSessionId, card) {
      const current = getContext().state;
      if (requestSessionId !== current.sessionId || current.report) {
        throw new ApiError('Активная сессия не найдена.', { status: 404 });
      }
      if (options.failSubmit) {
        await respond(null);
        throw new ApiError('Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.');
      }
      const report = scoreCard(card, current.sessionId);
      persist({ ...current, card, report, endedAt: new Date().toISOString() });
      await respond(null);
      return structuredClone(report);
    },
  };
}

export const studentMockApi = createStudentMockApi();
