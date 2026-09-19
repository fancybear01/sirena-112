import { ApiError } from '../../../api/errors';
import {
  getBrowserStorage,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from '../../../api/mockStorage';
import type { CardCalculation, OperatorCard, Session } from '../../../api/types';
import { scenarioFixtures } from '../../teacher/api/scenarios.fixture';
import {
  assignedScenarioFixture,
  createReferenceCardForm,
  referenceExpectedInput,
  referenceQuestions,
  referenceRoutedServices,
  referenceSignPath,
} from './student.fixture';
import type {
  ScoreCriterion,
  StudentApi,
  StudentAssignment,
  StudentCardInput,
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
  timeLimitSeconds: number;
  cardRevision: number;
  card: OperatorCard;
  report: StudentSessionReport | null;
};

const fallbackSessionId = 'a13e08ea-220f-458a-95f6-95b7c3a3f14c';

export function createEmptyStudentInput(): StudentCardInput {
  return {
    caller: null,
    incident: null,
    address: null,
    description: null,
    victims: null,
    facts: {},
  };
}

export function createEmptyStudentCard(): OperatorCard {
  return { input: createEmptyStudentInput(), calculation: null };
}

function isStoredState(value: unknown): value is StoredStudentState {
  if (!value || typeof value !== 'object') return false;
  const state = value as Partial<StoredStudentState>;
  return typeof state.sessionId === 'string'
    && typeof state.scenarioId === 'string'
    && typeof state.startedAt === 'string'
    && (state.endedAt === null || typeof state.endedAt === 'string')
    && typeof state.timeLimitSeconds === 'number'
    && typeof state.cardRevision === 'number'
    && Boolean(state.card && typeof state.card === 'object' && 'input' in state.card)
    && (state.report === null || Boolean(state.report && typeof state.report === 'object'));
}

function isEmptyInput(input: StudentCardInput) {
  return !input.caller
    && !input.incident
    && !input.address
    && !input.description
    && !input.victims
    && Object.keys(input.facts).length === 0;
}

function calculateCard(input: StudentCardInput): CardCalculation {
  const selected = input.incident?.selectedSignIds ?? [];
  const prefixMatches = selected.every((id, index) => referenceSignPath[index] === id);
  if (!prefixMatches) {
    return {
      status: 'NO_MATCH',
      classifierVersion: '046-2024-11-15',
      classifierCode: null,
      incidentType: null,
      ekp35IncidentType: null,
      responseScenarioCode: null,
      responseScenarioStatus: null,
      mainServices: [],
      services: [],
      missingInputIds: [],
      explanations: ['Комбинация признаков не найдена в учебном классификаторе.'],
    };
  }
  if (selected.length < referenceSignPath.length) {
    return {
      status: 'INCOMPLETE',
      classifierVersion: '046-2024-11-15',
      classifierCode: null,
      incidentType: null,
      ekp35IncidentType: null,
      responseScenarioCode: null,
      responseScenarioStatus: null,
      mainServices: [],
      services: [],
      missingInputIds: [`signs.level${selected.length + 1}`],
      explanations: ['Путь признаков не завершён: выберите следующее уточнение.'],
    };
  }
  const answered = new Set(input.incident?.answers.map((answer) => answer.questionId) ?? []);
  return {
    status: 'RESOLVED',
    classifierVersion: '046-2024-11-15',
    classifierCode: '1050602',
    incidentType: 'задымление: мусоропровод',
    ekp35IncidentType: 'пожар: мусоропровод',
    responseScenarioCode: '1_9',
    responseScenarioStatus: 'CODE',
    mainServices: [{ id: 'MCHS', displayName: 'Служба 101 (МЧС)' }],
    services: referenceRoutedServices,
    missingInputIds: referenceQuestions.filter((question) => !answered.has(question.id)).map((question) => question.id),
    explanations: [
      'Совпадение с записью классификатора 1050602 (задымление: мусоропровод).',
      'Службы определены правилами маршрутизации каталога.',
    ],
  };
}

function scoreCard(input: StudentCardInput, calculation: CardCalculation, sessionId: string): StudentSessionReport {
  const expectedAnswers = new Map(referenceExpectedInput.incident!.answers.map((answer) => [
    answer.questionId,
    answer.optionIds ?? [],
  ]));
  const actualAnswers = new Map(input.incident?.answers.map((answer) => [answer.questionId, answer.optionIds ?? []]) ?? []);
  const signsPassed = referenceSignPath.every((id, index) => input.incident?.selectedSignIds[index] === id);
  const answersPassed = [...expectedAnswers].every(([id, options]) => (
    JSON.stringify(actualAnswers.get(id)) === JSON.stringify(options)
  ));
  const servicesPassed = calculation.status === 'RESOLVED'
    && calculation.services.map((service) => service.id).join('|') === referenceRoutedServices.map((service) => service.id).join('|');
  const addressPassed = Boolean(input.address?.displayAddress.trim());
  const checks = [
    ['SIGNS', signsPassed, 'Признаки соответствуют эталонному пути классификатора.'],
    ['ANSWERS', answersPassed, 'Ответы на дополнительные вопросы соответствуют сценарию.'],
    ['SERVICES', servicesPassed, 'Службы вычислены по правилам Core.'],
    ['ADDRESS', addressPassed, 'Адрес происшествия зафиксирован.'],
  ] as const;
  const criteria: ScoreCriterion[] = checks.map(([code, passed, success]) => ({
    code,
    passed,
    points: passed ? 25 : 0,
    maxPoints: 25,
    message: passed ? success : `Проверьте раздел «${code}».`,
  }));
  const errors = criteria.filter((criterion) => !criterion.passed).map((criterion) => ({
    code: `CRITERION_${criterion.code}`,
    message: criterion.message,
    field: criterion.code.toLocaleLowerCase('ru-RU'),
  }));
  const score = criteria.reduce((total, criterion) => total + criterion.points, 0);
  return {
    sessionId,
    score,
    maxScore: 100,
    passed: errors.length === 0,
    criteria,
    errors,
    recommendations: errors.length
      ? errors.map((error) => `Проверьте исходные данные раздела ${error.field}.`)
      : ['Сохраняйте порядок: признаки, вопросы, адрес и сведения о пострадавших.'],
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

  function readState(sessionId: string, scenarioId: string, startedAt: string, timeLimitSeconds: number): StoredStudentState {
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
      timeLimitSeconds,
      cardRevision: 0,
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
    const timeLimitSeconds = scenario.timeLimitSeconds ?? 30;
    if (!state || state.sessionId !== sessionId) {
      state = readState(sessionId, scenarioId, startedAt, timeLimitSeconds);
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
    const finishedAt = current.endedAt ? Date.parse(current.endedAt) : Date.now();
    const elapsedSeconds = Math.max(0, Math.floor((finishedAt - Date.parse(current.startedAt)) / 1000));
    return {
      id: current.sessionId,
      scenarioId: current.scenarioId,
      mode: 'CARD',
      state: current.report ? 'SCORED' : 'ACTIVE',
      card: structuredClone(current.card),
      cardRevision: current.cardRevision,
      report: structuredClone(current.report),
      startedAt: current.startedAt,
      endedAt: current.endedAt,
      timeLimitSeconds: current.timeLimitSeconds,
      timeLimitExceeded: elapsedSeconds > current.timeLimitSeconds,
    };
  }

  async function respond<T>(value: T): Promise<T> {
    if (delayMs > 0) await new Promise((resolve) => window.setTimeout(resolve, delayMs));
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

    async getCardForm(sessionId) {
      const current = getContext().state;
      if (sessionId !== current.sessionId) throw new ApiError('Активная сессия не найдена.', { status: 404 });
      return respond(createReferenceCardForm(current.card.input.incident?.selectedSignIds));
    },

    async saveCard(requestSessionId, input, expectedRevision) {
      const current = getContext().state;
      if (requestSessionId !== current.sessionId || current.report) {
        throw new ApiError('Активная сессия не найдена.', { status: 404 });
      }
      if (expectedRevision !== undefined && expectedRevision !== current.cardRevision) {
        throw new ApiError('Черновик уже изменён в другой вкладке.', { status: 409 });
      }
      if (isEmptyInput(input)) throw new ApiError('Карточка должна содержать хотя бы одно заполненное поле.');
      if (options.failSave) {
        await respond(null);
        throw new ApiError('Не удалось сохранить черновик.');
      }
      const card = { input, calculation: calculateCard(input) };
      persist({ ...current, card, cardRevision: current.cardRevision + 1, report: null });
      return respond(makeSession(state!));
    },

    async submitCard(requestSessionId, input, expectedRevision) {
      const current = getContext().state;
      if (requestSessionId !== current.sessionId || current.report) {
        throw new ApiError('Активная сессия не найдена.', { status: 404 });
      }
      if (expectedRevision !== undefined && expectedRevision !== current.cardRevision) {
        throw new ApiError('Черновик уже изменён в другой вкладке.', { status: 409 });
      }
      if (options.failSubmit) {
        await respond(null);
        throw new ApiError('Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.');
      }
      const calculation = calculateCard(input);
      if (calculation.status !== 'RESOLVED' || calculation.missingInputIds.length > 0
        || !input.address?.displayAddress.trim() || input.victims === null) {
        throw new ApiError('Не заполнены обязательные поля карточки.', { status: 400 });
      }
      const report = scoreCard(input, calculation, current.sessionId);
      persist({
        ...current,
        card: { input, calculation },
        cardRevision: current.cardRevision + (JSON.stringify(input) === JSON.stringify(current.card.input) ? 0 : 1),
        report,
        endedAt: new Date().toISOString(),
      });
      await respond(null);
      return structuredClone(report);
    },
  };
}

export const studentMockApi = createStudentMockApi();
