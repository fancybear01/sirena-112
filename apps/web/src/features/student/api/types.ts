import type {
  OperatorCard,
  Scenario,
  ScoreCriterion as CoreScoreCriterion,
  ScoreError as CoreScoreError,
  Session,
  SessionReport,
} from '../../../api/types';

export type StudentScenario = Scenario;
export type StudentOperatorCard = OperatorCard;
export type ScoreCriterion = CoreScoreCriterion;
export type ScoreError = CoreScoreError;
export type StudentSessionReport = SessionReport;

export type StudentSession = Omit<Session, 'state' | 'startedAt' | 'endedAt'> & {
  state: 'ACTIVE' | 'SCORING' | 'SCORED';
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
