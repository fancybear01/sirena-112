import { describe, expect, it, vi } from 'vitest';
import type { HttpClient } from './httpClient';
import { createStudentHttpApi } from '../features/student/api/studentHttpApi';
import { createStudentMockApi } from '../features/student/api/studentMockApi';
import { createTeacherHttpApi } from '../features/teacher/api/teacherHttpApi';
import { ApiError } from './errors';

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
  card: {
    input: {
      caller: null,
      incident: null,
      address: null,
      description: null,
      victims: null,
      facts: {},
    },
    calculation: null,
  },
  cardRevision: 0,
  report: null,
  startedAt: '2026-09-17T12:00:00.000Z',
  endedAt: null,
  timeLimitSeconds: 600,
  timeLimitExceeded: false,
};

const cardForm = {
  classifierVersion: '046-2024-11-15',
  signGroups: [{
    id: 'signs.level1',
    label: 'Группа происшествия',
    level: 1,
    required: true,
    options: [{ id: 'sign.house', label: 'Жилой дом' }],
  }],
  questions: [],
};

const serviceAssignment = {
  id: '10000000-0000-4000-8000-000000000001',
  sessionId: activeSession.id,
  serviceId: 'MCHS',
  displayName: 'Служба 101 (МЧС)',
  cardRevision: 1,
  status: 'ADDED',
  createdAt: '2026-09-23T10:00:00.000Z',
  updatedAt: '2026-09-23T10:00:00.000Z',
  deadlineAt: '2026-09-23T11:00:00.000Z',
  overdue: false,
  history: [{
    eventId: '20000000-0000-4000-8000-000000000001',
    sequence: 1,
    fromStatus: null,
    status: 'ADDED',
    timestamp: '2026-09-23T10:00:00.000Z',
    source: 'SYSTEM',
    comment: null,
    refusalReason: null,
  }],
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

  it('restores the teacher session from Core after page reload', async () => {
    const storage = {
      getItem: vi.fn().mockReturnValue(JSON.stringify(activeSession)),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    } as unknown as Storage;
    const scored = { ...activeSession, state: 'SCORED', report: {
      sessionId: activeSession.id, score: 100, maxScore: 100, passed: true,
      criteria: [], errors: [], recommendations: [],
    } };
    const request = vi.fn().mockResolvedValue(scored);
    const api = createTeacherHttpApi({ baseUrl: '' }, { request } as HttpClient, storage);

    await expect(api.getCurrentSession()).resolves.toMatchObject({
      state: 'SCORED', report: { score: 100 },
    });
    expect(request).toHaveBeenCalledWith(`/api/student/sessions/${activeSession.id}`);
    expect(storage.setItem).toHaveBeenCalled();
  });

  it('clears a stale teacher session only when Core confirms 404', async () => {
    const storage = {
      getItem: vi.fn().mockReturnValue(JSON.stringify(activeSession)),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    } as unknown as Storage;
    const request = vi.fn().mockRejectedValueOnce(new ApiError('Unavailable', { status: 503 }))
      .mockRejectedValueOnce(new ApiError('Missing', { status: 404 }));
    const api = createTeacherHttpApi({ baseUrl: '' }, { request } as HttpClient, storage);

    await expect(api.getCurrentSession()).rejects.toMatchObject({ status: 503 });
    expect(storage.removeItem).not.toHaveBeenCalled();
    await expect(api.getCurrentSession()).resolves.toBeNull();
    expect(storage.removeItem).toHaveBeenCalled();
  });

  it('adapts a student assignment, card form, DDS statuses and input-only submit payload', async () => {
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
      .mockResolvedValueOnce(cardForm)
      .mockResolvedValueOnce([serviceAssignment])
      .mockResolvedValueOnce({ ...activeSession, cardRevision: 1 })
      .mockResolvedValueOnce(report);
    const api = createStudentHttpApi(
      { baseUrl: 'https://core.example.test' },
      { request } as HttpClient,
    );

    const assignment = await api.getAssignment();
    await expect(api.getCardForm(assignment.session.id)).resolves.toMatchObject({ classifierVersion: '046-2024-11-15' });
    await expect(api.getServiceAssignments(assignment.session.id)).resolves.toEqual([serviceAssignment]);
    await expect(api.saveCard(assignment.session.id, assignment.session.card.input, 0)).resolves.toMatchObject({ cardRevision: 1 });
    await expect(api.submitCard(assignment.session.id, assignment.session.card.input, 1)).resolves.toEqual(report);
    expect(request).toHaveBeenNthCalledWith(1, '/api/student/assignments');
    expect(request).toHaveBeenNthCalledWith(
      3,
      `/api/student/sessions/${activeSession.id}/service-assignments`,
    );
    expect(request).toHaveBeenNthCalledWith(
      4,
      `/api/student/sessions/${activeSession.id}/card`,
      { method: 'PATCH', body: { input: assignment.session.card.input, expectedRevision: 0 } },
    );
    expect(request).toHaveBeenNthCalledWith(
      5,
      `/api/student/sessions/${activeSession.id}/submit`,
      { method: 'POST', body: { input: assignment.session.card.input, expectedRevision: 1 } },
    );
  });

  it('returns the same domain shapes from mock and HTTP adapters', async () => {
    const mockApi = createStudentMockApi({ delayMs: 0, storage: null });
    const mockAssignment = await mockApi.getAssignment();
    const mockForm = await mockApi.getCardForm(mockAssignment.session.id);
    const request = vi.fn()
      .mockResolvedValueOnce([structuredClone(mockAssignment)])
      .mockResolvedValueOnce(structuredClone(mockForm))
      .mockResolvedValueOnce([]);
    const httpApi = createStudentHttpApi(
      { baseUrl: 'https://core.example.test' },
      { request } as HttpClient,
      null,
    );

    await expect(httpApi.getAssignment()).resolves.toEqual(mockAssignment);
    await expect(httpApi.getCardForm(mockAssignment.session.id)).resolves.toEqual(mockForm);
    await expect(httpApi.getServiceAssignments(mockAssignment.session.id)).resolves.toEqual([]);
  });
});
