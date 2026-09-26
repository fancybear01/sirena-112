import type {
  OperatorCard,
  Scenario,
  ScenarioDifficulty as CoreScenarioDifficulty,
  ServiceAssignment,
  Session,
  SessionEvent,
  SessionState as CoreSessionState,
} from '../../../api/types';

export type ScenarioDifficulty = CoreScenarioDifficulty;
export type ScenarioStatus = 'READY' | 'DRAFT';
export type SessionState = CoreSessionState;
export type TeacherServiceAssignment = ServiceAssignment;
export type TeacherSessionEvent = SessionEvent;

export type TeacherLiveConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'polling';

export interface TeacherSessionEvents {
  subscribe(
    sessionId: string,
    onEvent: (event: TeacherSessionEvent) => void,
    onConnectionState: (state: TeacherLiveConnectionState) => void,
  ): () => void;
}

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
  getStudents?(): Promise<{ id: string; displayName: string; username: string }[]>;
  getScenarios(): Promise<TeacherScenario[]>;
  getCurrentSession(): Promise<TeacherSession | null>;
  getServiceAssignments(sessionId: string): Promise<TeacherServiceAssignment[]>;
  launchSession(scenarioId: string, studentId?: string): Promise<TeacherSession>;
  stopSession(sessionId: string): Promise<TeacherSession>;
  clearSession(): Promise<void>;
}
