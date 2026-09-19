import { ApiError } from './errors';
import {
  scenarioCategories,
  type CardCalculation,
  type OperatorCardInput,
  type OperatorCard,
  type RoutedService,
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
  const input = isRecord(card.input) ? card.input : {};
  const caller = isRecord(input.caller) ? input.caller : null;
  const incident = isRecord(input.incident) ? input.incident : null;
  const address = isRecord(input.address) ? input.address : null;
  const victims = isRecord(input.victims) ? input.victims : null;
  const normalizedInput: OperatorCardInput = {
    caller: caller ? {
      phoneNumbers: Array.isArray(caller.phoneNumbers)
        ? caller.phoneNumbers.filter(isRecord).flatMap((phone) => (
            typeof phone.value === 'string'
              ? [{
                  value: phone.value,
                  kind: phone.kind === 'AON' || phone.kind === 'ON_SCENE' ? phone.kind : 'PROVIDED' as const,
                  foreign: phone.foreign === true,
                }]
              : []
          ))
        : [],
      fullName: typeof caller.fullName === 'string' ? caller.fullName : null,
      status: typeof caller.status === 'string' ? caller.status as NonNullable<OperatorCardInput['caller']>['status'] : null,
      communicationChannel: typeof caller.communicationChannel === 'string'
        ? caller.communicationChannel as NonNullable<OperatorCardInput['caller']>['communicationChannel']
        : null,
      language: typeof caller.language === 'string' ? caller.language : null,
    } : null,
    incident: incident ? {
      selectedSignIds: Array.isArray(incident.selectedSignIds)
        ? incident.selectedSignIds.filter((item): item is string => typeof item === 'string')
        : [],
      answers: Array.isArray(incident.answers)
        ? incident.answers.filter(isRecord).flatMap((answer) => (
            typeof answer.questionId === 'string'
              ? [{
                  questionId: answer.questionId,
                  optionIds: Array.isArray(answer.optionIds)
                    ? answer.optionIds.filter((item): item is string => typeof item === 'string')
                    : undefined,
                  freeText: typeof answer.freeText === 'string' ? answer.freeText : undefined,
                }]
              : []
          ))
        : [],
    } : null,
    address: address && typeof address.displayAddress === 'string'
      ? address as OperatorCardInput['address']
      : null,
    description: typeof input.description === 'string' ? input.description : null,
    victims: victims && typeof victims.present === 'boolean'
      ? victims as OperatorCardInput['victims']
      : null,
    facts: isRecord(input.facts) ? input.facts : {},
  };

  const calculation = isRecord(card.calculation) ? card.calculation : null;
  const normalizeService = (service: unknown): RoutedService | null => {
    if (!isRecord(service) || typeof service.id !== 'string' || typeof service.displayName !== 'string') return null;
    return {
      id: service.id,
      displayName: service.displayName,
      reasons: Array.isArray(service.reasons)
        ? service.reasons.filter(isRecord).flatMap((reason) => (
            typeof reason.ruleId === 'string' && typeof reason.message === 'string'
              ? [{
                  ruleId: reason.ruleId,
                  message: reason.message,
                  matchedInputIds: Array.isArray(reason.matchedInputIds)
                    ? reason.matchedInputIds.filter((item): item is string => typeof item === 'string')
                    : [],
                }]
              : []
          ))
        : [],
    };
  };
  const normalizedCalculation: CardCalculation | null = calculation
    && (calculation.status === 'INCOMPLETE' || calculation.status === 'RESOLVED' || calculation.status === 'NO_MATCH')
    && typeof calculation.classifierVersion === 'string'
    ? {
        status: calculation.status,
        classifierVersion: calculation.classifierVersion,
        classifierCode: typeof calculation.classifierCode === 'string' ? calculation.classifierCode : null,
        incidentType: typeof calculation.incidentType === 'string' ? calculation.incidentType : null,
        ekp35IncidentType: typeof calculation.ekp35IncidentType === 'string' ? calculation.ekp35IncidentType : null,
        responseScenarioCode: typeof calculation.responseScenarioCode === 'string' ? calculation.responseScenarioCode : null,
        responseScenarioStatus: typeof calculation.responseScenarioStatus === 'string'
          ? calculation.responseScenarioStatus as CardCalculation['responseScenarioStatus']
          : null,
        mainServices: Array.isArray(calculation.mainServices)
          ? calculation.mainServices.filter(isRecord).flatMap((service) => (
              typeof service.id === 'string' && typeof service.displayName === 'string'
                ? [{ id: service.id, displayName: service.displayName }]
                : []
            ))
          : [],
        services: Array.isArray(calculation.services)
          ? calculation.services.map(normalizeService).filter((service): service is RoutedService => service !== null)
          : [],
        missingInputIds: Array.isArray(calculation.missingInputIds)
          ? calculation.missingInputIds.filter((item): item is string => typeof item === 'string')
          : [],
        explanations: Array.isArray(calculation.explanations)
          ? calculation.explanations.filter((item): item is string => typeof item === 'string')
          : [],
      }
    : null;

  return {
    input: normalizedInput,
    calculation: normalizedCalculation,
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
    cardRevision: typeof value.cardRevision === 'number' ? value.cardRevision : 0,
    report: isRecord(value.report) ? value.report as SessionReport : null,
    startedAt: typeof value.startedAt === 'string' ? value.startedAt : null,
    endedAt: typeof value.endedAt === 'string' ? value.endedAt : null,
    timeLimitSeconds: typeof value.timeLimitSeconds === 'number' ? value.timeLimitSeconds : 600,
    timeLimitExceeded: value.timeLimitExceeded === true,
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
