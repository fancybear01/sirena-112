import { assignedScenarioFixture } from './student.fixture';
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
  startedAt: string;
  card: StudentOperatorCard;
  report: StudentSessionReport | null;
};

export const studentDraftStorageKey = 'sirena-112:student-assignment';

const sessionId = 'a13e08ea-220f-458a-95f6-95b7c3a3f14c';

export function createEmptyStudentCard(): StudentOperatorCard {
  return {
    incidentType: null,
    signs: null,
    address: null,
    requiredServices: [],
    facts: { description: '' },
  };
}

function getBrowserStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function isStoredState(value: unknown): value is StoredStudentState {
  if (!value || typeof value !== 'object') return false;
  const state = value as Partial<StoredStudentState>;
  return typeof state.startedAt === 'string'
    && Boolean(state.card && typeof state.card === 'object')
    && (state.report === null || Boolean(state.report && typeof state.report === 'object'));
}

function scoreCard(card: StudentOperatorCard): StudentSessionReport {
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

  function readState(): StoredStudentState {
    if (storage) {
      try {
        const raw = storage.getItem(studentDraftStorageKey);
        if (raw) {
          const parsed: unknown = JSON.parse(raw);
          if (isStoredState(parsed)) return parsed;
          storage.removeItem(studentDraftStorageKey);
        }
      } catch {
        // Unavailable or corrupted storage falls back to an empty in-memory assignment.
      }
    }
    return { startedAt: new Date().toISOString(), card: createEmptyStudentCard(), report: null };
  }

  let state = readState();

  function persist(next: StoredStudentState) {
    state = structuredClone(next);
    if (!storage) return;
    try {
      storage.setItem(studentDraftStorageKey, JSON.stringify(state));
    } catch {
      // The demonstration remains usable in memory when localStorage is unavailable.
    }
  }

  function makeSession(): StudentSession {
    return {
      id: sessionId,
      scenarioId: assignedScenarioFixture.id,
      mode: 'CARD',
      state: state.report ? 'SCORED' : 'ACTIVE',
      card: structuredClone(state.card),
      report: structuredClone(state.report),
      startedAt: state.startedAt,
      endedAt: state.report ? new Date().toISOString() : null,
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
        throw new Error('Mock assignment request failed');
      }
      return respond({ scenario: assignedScenarioFixture, session: makeSession() });
    },

    async saveCard(requestSessionId, card) {
      if (requestSessionId !== sessionId || state.report) throw new Error('Active session not found');
      if (options.failSave) {
        await respond(null);
        throw new Error('Mock card save failed');
      }
      persist({ ...state, card, report: null });
      return respond(makeSession());
    },

    async submitCard(requestSessionId, card) {
      if (requestSessionId !== sessionId || state.report) throw new Error('Active session not found');
      if (options.failSubmit) {
        await respond(null);
        throw new Error('Mock submit failed');
      }
      const report = scoreCard(card);
      persist({ ...state, card, report });
      await respond(null);
      return structuredClone(report);
    },
  };
}

export const studentMockApi = createStudentMockApi();
