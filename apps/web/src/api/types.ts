export const scenarioCategories = [
  'FIRE',
  'ACCIDENT',
  'EXPLOSION',
  'EXPLOSION_THREAT',
  'COLLAPSE',
  'COLLAPSE_THREAT',
  'NATURAL_HAZARD',
  'ENVIRONMENT',
  'HYDRAULIC_FACILITY',
  'INDUSTRIAL_ACCIDENT',
  'HAZMAT_THREAT',
  'TRANSPORT_FACILITY',
  'GAS',
  'UTILITY',
  'PUBLIC_ORDER',
  'ROAD_CONDITION',
  'PERSON_AT_RISK',
  'CHILD_AT_RISK',
  'DEATH',
  'SOCIAL_AID',
  'ANIMAL',
  'MEDICAL',
  'OTHER',
] as const;

export type ScenarioCategory = (typeof scenarioCategories)[number];
export type ScenarioDifficulty = 'BASIC' | 'INTERMEDIATE' | 'ADVANCED';

export type IncidentSigns = {
  level1: string;
  level2?: string | null;
  level3?: string | null;
  additional?: string[];
};

export type ScenarioGroundTruth = {
  incidentType: string;
  ekpCode?: string;
  signs?: IncidentSigns;
  address?: string | null;
  requiredServices: string[];
  facts?: Record<string, unknown>;
  [key: string]: unknown;
};

export type ScenarioRubricCriterion = {
  code: string;
  description: string;
  weight: number;
  critical?: boolean;
};

export type ScenarioRubric = {
  criteria: ScenarioRubricCriterion[];
};

// Matches components.schemas.Scenario and the stricter contracts/scenario.schema.json.
export type Scenario = {
  id: string;
  version: number;
  title: string;
  category: ScenarioCategory;
  difficulty: ScenarioDifficulty;
  profile: string;
  timeLimitSeconds?: number;
  groundTruth: ScenarioGroundTruth;
  rubric: ScenarioRubric;
};

export type OperatorCard = {
  incidentType: string | null;
  signs: IncidentSigns | null;
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

export type SessionReport = {
  sessionId: string;
  score: number;
  maxScore: number;
  passed: boolean;
  criteria: ScoreCriterion[];
  errors: ScoreError[];
  recommendations: string[];
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

// startedAt/endedAt are optional client extensions until they are described in OpenAPI.
export type Session = {
  id: string;
  scenarioId: string;
  mode: 'CARD';
  state: SessionState;
  card: OperatorCard;
  report: SessionReport | null;
  startedAt?: string | null;
  endedAt?: string | null;
};

// The assignments endpoint has no response schema yet; this is the UI-facing adapter model.
export type StudentAssignment = {
  scenario: Scenario;
  session: Session & { startedAt: string };
};
