import { describe, expect, it, vi } from 'vitest';
import type { HttpClient } from './httpClient';
import { createStudentHttpApi } from '../features/student/api/studentHttpApi';
import { createTeacherHttpApi } from '../features/teacher/api/teacherHttpApi';

const scenario = {
  id: '0c44dd40-9423-4e58-8905-fc7b45c26dd4',
  version: 1,
  title: 'Пожар в жилом доме',
  category: 'FIRE',
  difficulty: 'BASIC',
  profile: 'Описание сценария',
  timeLimitSeconds: 600,
  groundTruth: { incidentType: 'FIRE', requiredServices: ['FIRE'] },
  rubric: { criteria: [{ code: 'TYPE', description: 'Тип', weight: 1 }] },
};

const activeSession = {
  id: 'a13e08ea-220f-458a-95f6-95b7c3a3f14c',
  scenarioId: scenario.id,
  mode: 'CARD',
  state: 'ACTIVE',
  card: {},
  report: null,
  startedAt: '2026-09-17T12:00:00.000Z',
};

describe('Core API adapters', () => {
  it('creates and starts a teacher session through contract endpoints', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ ...activeSession, state: 'CREATED' })
      .mockResolvedValueOnce(activeSession);
    const api = createTeacherHttpApi(
      { baseUrl: 'https://core.example.test' },
      { request } as HttpClient,
      null,
    );

    await expect(api.launchSession(scenario.id)).resolves.toMatchObject({ state: 'ACTIVE' });
    expect(request).toHaveBeenNthCalledWith(1, '/api/teacher/sessions', {
      method: 'POST',
      body: { scenarioId: scenario.id },
    });
    expect(request).toHaveBeenNthCalledWith(
      2,
      `/api/teacher/sessions/${activeSession.id}/start`,
      { method: 'POST' },
    );
  });

  it('adapts a student assignment and sends the card as JSON payload', async () => {
    const report = {
      sessionId: activeSession.id,
      score: 100,
      maxScore: 100,
      passed: true,
      criteria: [],
      errors: [],
      recommendations: [],
    };
    const request = vi.fn()
      .mockResolvedValueOnce([{ scenario, session: activeSession }])
      .mockResolvedValueOnce(report);
    const api = createStudentHttpApi(
      { baseUrl: 'https://core.example.test' },
      { request } as HttpClient,
    );

    const assignment = await api.getAssignment();
    await expect(api.submitCard(assignment.session.id, assignment.session.card)).resolves.toEqual(report);
    expect(request).toHaveBeenNthCalledWith(1, '/api/student/assignments');
    expect(request).toHaveBeenNthCalledWith(
      2,
      `/api/student/sessions/${activeSession.id}/submit`,
      { method: 'POST', body: assignment.session.card },
    );
  });
});
