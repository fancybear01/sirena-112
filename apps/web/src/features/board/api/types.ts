import type { SessionState, TrainingAnalyticsSummary } from '../../../api/types';

export type TrainingBoardState = Exclude<SessionState, 'COMPLETED' | 'SCORED' | 'FAILED'>;

export type TrainingBoardSession = {
  scenarioTitle: string;
  mode: 'CARD' | 'VOICE';
  state: TrainingBoardState;
  startedAt: string | null;
  updatedAt: string;
};

export type TrainingBoardSnapshot = {
  generatedAt: string;
  activeSessions: TrainingBoardSession[];
  analytics: TrainingAnalyticsSummary;
};

export interface TrainingBoardApi {
  getSnapshot(): Promise<TrainingBoardSnapshot>;
}
