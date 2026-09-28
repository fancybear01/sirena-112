// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { TrainingHistoryPanel } from './TrainingHistoryPanel';

beforeAll(() => {
  globalThis.ResizeObserver = class implements ResizeObserver { observe() {} unobserve() {} disconnect() {} };
  window.matchMedia = (query) => ({ matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
    removeEventListener: () => {}, dispatchEvent: () => false });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('TrainingHistoryPanel', () => {
  it('shows factual result and lets teacher add feedback', async () => {
    const attempt = { sessionId: 'one', studentName: 'Студент', scenarioTitle: 'Пожар', scenarioProfile: 'Учебная карточка',
      scenarioVersion: 1, state: 'SCORED', createdAt: '2026-09-28T10:00:00Z', elapsedSeconds: 34,
      timeLimitSeconds: 30, exceededLimit: true, effectiveScore: 75, feedback: [],
      originalReport: { sessionId: 'one', score: 60, maxScore: 100, passed: false, criteria: [], errors: [], recommendations: [] },
      comparison: { expectedClassifierCode: '1050602', actualClassifierCode: '1050602', classifierMatches: true,
        expectedServiceIds: ['MCHS'], actualServiceIds: ['MCHS'], servicesMatch: true,
        expectedAnswers: {}, actualAnswers: {}, answersMatch: true, finalTranscript: [] } };
    const request = vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'POST' ? attempt :
      { summary: { assigned: 1, completed: 1, averagePercent: 75 }, attempts: [attempt] }),
      { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', request);
    render(<MantineProvider><TrainingHistoryPanel role="teacher" /></MantineProvider>);
    expect(await screen.findByText(/Эталон классификатора: 1050602/)).toBeInTheDocument();
    expect(screen.getByText(/Исходная оценка: 60/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Комментарий обучающемуся'), 'Повторите алгоритм');
    await userEvent.click(screen.getByRole('button', { name: 'Добавить комментарий' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.stringContaining('/api/teacher/history/one/comments'),
      expect.objectContaining({ method: 'POST' })));
  });
});
