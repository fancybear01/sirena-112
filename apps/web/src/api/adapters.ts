import { ApiError } from './errors';
import {
  scenarioCategories,
  type OperatorCard,
  type Scenario,
  type Session,
  type SessionReport,
  type SessionState,
} from './types';

const sessionStates: SessionState[] = [
  'CREATED', 'READY', 'RINGING', 'ACTIVE', 'COMPLETED', 'SCORING', 'SCORED', 'FAILED',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new ApiError(`Core API вернул некорректное поле «${field}».`, { code: 'INVALID_RESPONSE' });
  }
  return value;
}

export function normalizeOperatorCard(value: unknown): OperatorCard {
  const card = isRecord(value) ? value : {};
  const facts = isRecord(card.facts) ? card.facts : {};
  return {
    incidentType: typeof card.incidentType === 'string' ? card.incidentType : null,
    signs: isRecord(card.signs) && typeof card.signs.level1 === 'string'
      ? {
          level1: card.signs.level1,
          level2: typeof card.signs.level2 === 'string' ? card.signs.level2 : null,
          level3: typeof card.signs.level3 === 'string' ? card.signs.level3 : null,
          additional: Array.isArray(card.signs.additional)
            ? card.signs.additional.filter((item): item is string => typeof item === 'string')
            : [],
        }
      : null,
    address: typeof card.address === 'string' ? card.address : null,
    requiredServices: Array.isArray(card.requiredServices)
      ? card.requiredServices.filter((item): item is string => typeof item === 'string')
      : [],
    facts,
  };
}

export function normalizeSession(value: unknown): Session {
  if (!isRecord(value)) {
    throw new ApiError('Core API вернул некорректную сессию.', { code: 'INVALID_RESPONSE' });
  }
  const state = requireString(value.state, 'session.state');
  if (!sessionStates.includes(state as SessionState)) {
    throw new ApiError('Core API вернул неизвестное состояние сессии.', { code: 'INVALID_RESPONSE' });
  }
  return {
    id: requireString(value.id, 'session.id'),
    scenarioId: requireString(value.scenarioId, 'session.scenarioId'),
    mode: 'CARD',
    state: state as SessionState,
    card: normalizeOperatorCard(value.card),
    report: isRecord(value.report) ? value.report as SessionReport : null,
    startedAt: typeof value.startedAt === 'string' ? value.startedAt : null,
    endedAt: typeof value.endedAt === 'string' ? value.endedAt : null,
  };
}

export function normalizeScenario(value: unknown): Scenario {
  if (!isRecord(value) || !isRecord(value.groundTruth) || !isRecord(value.rubric)) {
    throw new ApiError('Core API вернул некорректный сценарий.', { code: 'INVALID_RESPONSE' });
  }
  if (!Array.isArray(value.groundTruth.requiredServices) || !Array.isArray(value.rubric.criteria)) {
    throw new ApiError('Core API вернул сценарий, не соответствующий контракту.', { code: 'INVALID_RESPONSE' });
  }
  if (!scenarioCategories.includes(value.category as Scenario['category'])) {
    throw new ApiError('Core API вернул неизвестную категорию сценария.', { code: 'INVALID_RESPONSE' });
  }
  requireString(value.id, 'scenario.id');
  requireString(value.title, 'scenario.title');
  requireString(value.profile, 'scenario.profile');
  return value as Scenario;
}

export function normalizeReport(value: unknown): SessionReport {
  if (!isRecord(value) || !Array.isArray(value.criteria)
    || !Array.isArray(value.errors) || !Array.isArray(value.recommendations)) {
    throw new ApiError('Core API вернул некорректный отчёт.', { code: 'INVALID_RESPONSE' });
  }
  return value as SessionReport;
}
