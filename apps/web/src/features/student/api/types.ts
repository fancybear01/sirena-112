export type StudentScenario = {
  id: string;
  version: number;
  title: string;
  category: string;
  difficulty: 'BASIC' | 'INTERMEDIATE' | 'ADVANCED';
  profile: string;
  timeLimitSeconds: number;
};

// Mirrors components.schemas.OperatorCard from contracts/openapi.yaml.
export type StudentOperatorCard = {
  incidentType: string | null;
  signs: Record<string, unknown> | null;
  address: string | null;
  requiredServices: string[];
  facts: {
    description?: string;
    [key: string]: unknown;
  };
};

export type ScoreCriterion = {
  code: string;
  passed: boolean;
  points: number;
  maxPoints: number;
  message: string;
};

export type ScoreError = {
  code: string;
  message: string;
  field: string | null;
};

// Mirrors components.schemas.SessionReport from contracts/openapi.yaml.
export type StudentSessionReport = {
  sessionId: string;
  score: number;
  maxScore: number;
  passed: boolean;
  criteria: ScoreCriterion[];
  errors: ScoreError[];
  recommendations: string[];
};

export type StudentSession = {
  id: string;
  scenarioId: string;
  mode: 'CARD';
  state: 'ACTIVE' | 'SCORING' | 'SCORED';
  card: StudentOperatorCard;
  report: StudentSessionReport | null;
  startedAt: string;
  endedAt: string | null;
};

export type StudentAssignment = {
  scenario: StudentScenario;
  session: StudentSession;
};

export interface StudentApi {
  getAssignment(): Promise<StudentAssignment>;
  saveCard(sessionId: string, card: StudentOperatorCard): Promise<StudentSession>;
  submitCard(sessionId: string, card: StudentOperatorCard): Promise<StudentSessionReport>;
}
