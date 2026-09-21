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
  classifierVersion?: string;
  classifierCode?: string;
  ekp35IncidentType?: string | null;
  responseScenarioCode?: string | null;
  responseScenarioStatus?: 'CODE' | 'MISSING' | 'EXPLICIT_NONE' | 'SOURCE_LABEL';
  signs?: IncidentSigns;
  address?: string | null;
  mainServices?: ServiceRef[];
  requiredServices: Array<string | RoutedService>;
  expectedInput?: OperatorCardInput;
  facts?: Record<string, unknown>;
  [key: string]: unknown;
};

export type PhoneNumber = {
  value: string;
  kind: 'AON' | 'PROVIDED' | 'ON_SCENE';
  foreign?: boolean;
};

export type CallerInput = {
  phoneNumbers: PhoneNumber[];
  fullName: string | null;
  status: 'EYEWITNESS' | 'VICTIM' | 'RELATIVE' | 'ACQUAINTANCE' | 'CHILD' | 'PARTICIPANT' | 'OTHER' | null;
  communicationChannel: 'VOICE' | 'SMS' | 'OTHER' | null;
  language: string | null;
};

export type QuestionAnswer = {
  questionId: string;
  optionIds?: string[];
  freeText?: string | null;
};

export type IncidentInput = {
  selectedSignIds: string[];
  answers: QuestionAnswer[];
};

export type AddressInput = {
  displayAddress: string;
  region?: string | null;
  locality?: string | null;
  street?: string | null;
  house?: string | null;
  building?: string | null;
  apartment?: string | null;
  description?: string | null;
  latitude?: number | null;
  longitude?: number | null;
};

export type VictimsInput = {
  present: boolean;
  count?: number | null;
  threatToPeople?: boolean | null;
};

export type OperatorCardInput = {
  caller: CallerInput | null;
  incident: IncidentInput | null;
  address: AddressInput | null;
  description: string | null;
  victims: VictimsInput | null;
  facts: Record<string, unknown>;
};

export type ServiceRef = {
  id: string;
  displayName: string;
};

export type RoutingReason = {
  ruleId: string;
  message: string;
  matchedInputIds: string[];
};

export type RoutedService = ServiceRef & {
  reasons: RoutingReason[];
};

export type CardCalculation = {
  status: 'INCOMPLETE' | 'RESOLVED' | 'NO_MATCH';
  classifierVersion: string;
  classifierCode: string | null;
  incidentType: string | null;
  ekp35IncidentType: string | null;
  responseScenarioCode: string | null;
  responseScenarioStatus: 'CODE' | 'MISSING' | 'EXPLICIT_NONE' | 'SOURCE_LABEL' | null;
  mainServices: ServiceRef[];
  services: RoutedService[];
  missingInputIds: string[];
  explanations: string[];
};

export type SelectionOption = {
  id: string;
  label: string;
};

export type SignGroup = {
  id: string;
  label: string;
  level: 1 | 2 | 3;
  required: boolean;
  options: SelectionOption[];
};

export type QuestionDefinition = {
  id: string;
  label: string;
  inputType: 'SINGLE_SELECT' | 'MULTI_SELECT' | 'TEXT';
  required: boolean;
  options: SelectionOption[];
};

export type CardFormDefinition = {
  classifierVersion: string;
  signGroups: SignGroup[];
  questions: QuestionDefinition[];
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
  input: OperatorCardInput;
  calculation: CardCalculation | null;
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
  classifierVersion?: string | null;
  classifierCode?: string | null;
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

export type Session = {
  id: string;
  scenarioId: string;
  mode: 'CARD';
  state: SessionState;
  card: OperatorCard;
  cardRevision: number;
  report: SessionReport | null;
  startedAt?: string | null;
  endedAt?: string | null;
  timeLimitSeconds: number;
  timeLimitExceeded: boolean;
};

export type StudentAssignment = {
  scenario: Scenario;
  session: Session & { startedAt: string };
};
