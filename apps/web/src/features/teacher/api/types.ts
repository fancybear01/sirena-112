export type ScenarioDifficulty = 'BASIC' | 'INTERMEDIATE' | 'ADVANCED';
export type ScenarioStatus = 'READY' | 'DRAFT';

// Mirrors components.schemas.Scenario from contracts/openapi.yaml.
export type Scenario = {
  id: string;
  version: number;
  title: string;
  category: string;
  difficulty: ScenarioDifficulty;
  profile: string;
  timeLimitSeconds?: number;
  groundTruth: Record<string, unknown>;
  rubric: Record<string, unknown>;
};

export type TeacherScenario = Scenario & {
  status: ScenarioStatus;
};

export type SessionState =
  | 'CREATED'
  | 'READY'
  | 'RINGING'
  | 'ACTIVE'
  | 'COMPLETED'
  | 'SCORING'
  | 'SCORED'
  | 'FAILED';

export type OperatorCard = {
  incidentType: string | null;
  signs: Record<string, unknown> | null;
  address: string | null;
  requiredServices: string[];
  facts: Record<string, unknown>;
};

// Base fields mirror components.schemas.Session from contracts/openapi.yaml.
export type TeacherSession = {
  id: string;
  scenarioId: string;
  mode: 'CARD';
  state: SessionState;
  card: OperatorCard;
  report: null;
  startedAt: string | null;
  endedAt: string | null;
};

export interface TeacherApi {
  getScenarios(): Promise<TeacherScenario[]>;
  launchSession(scenarioId: string): Promise<TeacherSession>;
  stopSession(sessionId: string): Promise<TeacherSession>;
}
