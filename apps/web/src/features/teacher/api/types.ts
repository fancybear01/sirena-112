import type {
  OperatorCard,
  Scenario,
  ScenarioDifficulty as CoreScenarioDifficulty,
  Session,
  SessionState as CoreSessionState,
} from '../../../api/types';

export type ScenarioDifficulty = CoreScenarioDifficulty;
export type ScenarioStatus = 'READY' | 'DRAFT';
export type SessionState = CoreSessionState;

// Readiness is a teacher-list presentation field; it is not part of Scenario in OpenAPI yet.
export type TeacherScenario = Scenario & {
  status: ScenarioStatus;
};

export type TeacherSession = Omit<Session, 'card' | 'startedAt' | 'endedAt'> & {
  card: OperatorCard;
  startedAt: string | null;
  endedAt: string | null;
};

export interface TeacherApi {
  getScenarios(): Promise<TeacherScenario[]>;
  getCurrentSession(): Promise<TeacherSession | null>;
  launchSession(scenarioId: string): Promise<TeacherSession>;
  stopSession(sessionId: string): Promise<TeacherSession>;
  clearSession(): Promise<void>;
}
