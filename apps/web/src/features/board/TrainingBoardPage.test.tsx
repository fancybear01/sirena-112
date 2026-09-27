// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { TrainingBoardPage } from './TrainingBoardPage';
import type { TrainingBoardApi, TrainingBoardSnapshot } from './api/types';

beforeAll(() => {
  globalThis.ResizeObserver = class implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
});

afterEach(cleanup);

const emptyAnalytics: TrainingBoardSnapshot['analytics'] = {
  completedSessions: 0,
  averagePercent: null,
  medianPercent: null,
  scoreDistribution: [
    { label: '0–20', count: 0 },
    { label: '>20–40', count: 0 },
    { label: '>40–60', count: 0 },
    { label: '>60–80', count: 0 },
    { label: '>80–100', count: 0 },
  ],
  incidentTypes: [],
  topErrors: [],
  daily: [],
};

function snapshot(overrides: Partial<TrainingBoardSnapshot> = {}): TrainingBoardSnapshot {
  return {
    generatedAt: '2026-09-28T12:00:00.000Z',
    activeSessions: [],
    analytics: emptyAnalytics,
    ...overrides,
  };
}

function renderBoard(api: TrainingBoardApi, pollIntervalMs = 3000) {
  return render(
    <MantineProvider>
      <TrainingBoardPage api={api} pollIntervalMs={pollIntervalMs} />
    </MantineProvider>,
  );
}

describe('training board', () => {
  it('shows an explicit empty state', async () => {
    renderBoard({ getSnapshot: vi.fn().mockResolvedValue(snapshot()) });

    expect(await screen.findByRole('heading', { name: 'Нет активных занятий' })).toBeInTheDocument();
    expect(screen.getByText('Новые процессы появятся здесь автоматически.')).toBeInTheDocument();
    expect(screen.getByText('Связь с Core')).toBeInTheDocument();
  });

  it('keeps the last snapshot and marks a connection loss', async () => {
    const current = snapshot({
      activeSessions: [{
        scenarioTitle: 'Учебный пожар',
        mode: 'CARD',
        state: 'ACTIVE',
        startedAt: '2026-09-28T11:50:00.000Z',
        updatedAt: '2026-09-28T11:59:00.000Z',
      }],
    });
    const getSnapshot = vi.fn().mockResolvedValueOnce(current).mockRejectedValue(new Error('offline'));
    renderBoard({ getSnapshot }, 20);

    expect(await screen.findByRole('heading', { name: 'Учебный пожар' })).toBeInTheDocument();
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('alert')).toHaveTextContent('Связь с Core потеряна');
    expect(screen.getByRole('heading', { name: 'Учебный пожар' })).toBeInTheDocument();
    expect(screen.getByText(/На экране сохранён последний успешный снимок/)).toBeInTheDocument();
  });

  it('replaces the snapshot on the next poll without a page reload', async () => {
    const first = snapshot({
      activeSessions: [{
        scenarioTitle: 'Карточка пожара',
        mode: 'CARD',
        state: 'ACTIVE',
        startedAt: '2026-09-28T11:50:00.000Z',
        updatedAt: '2026-09-28T11:59:00.000Z',
      }],
    });
    const updated = snapshot({
      generatedAt: '2026-09-28T12:00:03.000Z',
      activeSessions: [
        first.activeSessions[0],
        {
          scenarioTitle: 'Учебный звонок ДТП',
          mode: 'VOICE',
          state: 'RINGING',
          startedAt: null,
          updatedAt: '2026-09-28T12:00:02.000Z',
        },
      ],
      analytics: { ...emptyAnalytics, completedSessions: 7, averagePercent: 82 },
    });
    const getSnapshot = vi.fn().mockResolvedValueOnce(first).mockResolvedValue(updated);
    renderBoard({ getSnapshot }, 20);

    expect(await screen.findByText('В эфире: 1')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Учебный звонок ДТП' })).toBeInTheDocument();
    expect(screen.getByText('В эфире: 2')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });
});
