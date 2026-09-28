import type { TrainingBoardApi, TrainingBoardSnapshot } from './types';

type MockOptions = {
  delayMs?: number;
  snapshot?: TrainingBoardSnapshot;
};

const demoSnapshot: TrainingBoardSnapshot = {
  generatedAt: '2026-09-28T12:18:00.000Z',
  activeSessions: [
    {
      scenarioTitle: 'Задымление в жилом доме',
      mode: 'CARD',
      state: 'ACTIVE',
      startedAt: '2026-09-28T12:04:00.000Z',
      updatedAt: '2026-09-28T12:17:42.000Z',
    },
    {
      scenarioTitle: 'Дорожно-транспортное происшествие',
      mode: 'VOICE',
      state: 'RINGING',
      startedAt: null,
      updatedAt: '2026-09-28T12:17:55.000Z',
    },
  ],
  analytics: {
    completedSessions: 24,
    averagePercent: 78.4,
    medianPercent: 81,
    scoreDistribution: [
      { label: '0–20', count: 1 },
      { label: '>20–40', count: 2 },
      { label: '>40–60', count: 4 },
      { label: '>60–80', count: 8 },
      { label: '>80–100', count: 9 },
    ],
    incidentTypes: [],
    topErrors: [
      { criterionCode: 'ADDRESS', count: 5 },
      { criterionCode: 'SERVICES', count: 3 },
      { criterionCode: 'VICTIMS', count: 2 },
    ],
    daily: [],
  },
};

export function createTrainingBoardMockApi({
  delayMs = 120,
  snapshot = demoSnapshot,
}: MockOptions = {}): TrainingBoardApi {
  return {
    async getSnapshot() {
      if (delayMs > 0) await new Promise((resolve) => window.setTimeout(resolve, delayMs));
      return structuredClone({ ...snapshot, generatedAt: new Date().toISOString() });
    },
  };
}

export const trainingBoardMockApi = createTrainingBoardMockApi();
