import { describe, expect, it, vi } from 'vitest';
import type { HttpClient } from '../../../api/httpClient';
import { createTrainingBoardHttpApi } from './trainingBoardHttpApi';

describe('training board Core adapter', () => {
  it('loads the read-only board snapshot from the contract endpoint', async () => {
    const snapshot = {
      generatedAt: '2026-09-28T12:00:00.000Z',
      activeSessions: [],
      analytics: {
        completedSessions: 0,
        averagePercent: null,
        medianPercent: null,
        scoreDistribution: [],
        incidentTypes: [],
        topErrors: [],
        daily: [],
      },
    };
    const request = vi.fn().mockResolvedValue(snapshot);
    const api = createTrainingBoardHttpApi(
      { baseUrl: 'https://core.example.test' },
      { request } as HttpClient,
    );

    await expect(api.getSnapshot()).resolves.toEqual(snapshot);
    expect(request).toHaveBeenCalledWith('/api/teacher/board');
  });
});
