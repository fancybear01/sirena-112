// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { TeacherPage } from './TeacherPage';
import { createTeacherMockApi } from './api/teacherMockApi';
import { pollingTeacherSessionEvents } from './api/teacherSessionEvents';
import type { ServiceAssignment, ServiceStatus, SessionReport } from '../../api/types';
import type { TeacherAnalyticsSummary, TeacherApi, TeacherSessionEvents } from './api/types';

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

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderTeacher(
  api = createTeacherMockApi({ delayMs: 0 }),
  sessionEvents: TeacherSessionEvents = pollingTeacherSessionEvents,
  pollIntervalMs = 3000,
) {
  return render(
    <MantineProvider>
      <TeacherPage api={api} sessionEvents={sessionEvents} pollIntervalMs={pollIntervalMs} />
    </MantineProvider>,
  );
}

function makeServiceAssignment(
  id: string,
  displayName: string,
  status: ServiceStatus,
): ServiceAssignment {
  const timestamp = '2026-09-25T12:00:00.000Z';
  return {
    id,
    sessionId: 'placeholder-session',
    serviceId: id,
    displayName,
    cardRevision: 1,
    status,
    createdAt: timestamp,
    updatedAt: timestamp,
    deadlineAt: '2026-09-25T13:00:00.000Z',
    overdue: false,
    history: [{
      eventId: `event-${id}-${status}`,
      sequence: 1,
      fromStatus: status === 'ADDED' ? null : 'ADDED',
      status,
      timestamp,
      source: 'SYSTEM',
      comment: null,
      refusalReason: null,
    }],
  };
}

function makeAnalytics(overrides: Partial<TeacherAnalyticsSummary> = {}): TeacherAnalyticsSummary {
  return {
    completedSessions: 3,
    averagePercent: 68.3,
    medianPercent: 70,
    scoreDistribution: [
      { label: '0–20', count: 0 },
      { label: '>20–40', count: 0 },
      { label: '>40–60', count: 1 },
      { label: '>60–80', count: 1 },
      { label: '>80–100', count: 1 },
    ],
    incidentTypes: [{ code: '1050602', name: 'Задымление', count: 3 }],
    topErrors: [
      { criterionCode: 'ADDRESS', count: 2 },
      { criterionCode: 'VICTIMS', count: 1 },
    ],
    daily: [
      { day: '2026-09-26', count: 1, averagePercent: 55 },
      { day: '2026-09-27', count: 2, averagePercent: 75 },
    ],
    ...overrides,
  };
}

describe('teacher scenario flow', () => {
  it('renders a non-empty Core analytics summary with three views and its scope', async () => {
    renderTeacher(createTeacherMockApi({ analytics: makeAnalytics(), delayMs: 0 }));

    expect(await screen.findByText('Занятий: 3')).toBeInTheDocument();
    expect(screen.getByText('68,3%')).toBeInTheDocument();
    expect(screen.getByText('Выборка:').parentElement).toHaveTextContent('оценённые карточные занятия');
    expect(screen.getByText('Период UTC:').parentElement).toHaveTextContent('26 сент. — 27 сент.');
    expect(screen.getByRole('heading', { name: 'Динамика оценок' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Распределение результатов' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Частота ошибок по критериям' })).toHaveTextContent('ADDRESS');
  });

  it('renders an explicit empty analytics state instead of zero-result charts', async () => {
    renderTeacher(createTeacherMockApi({ delayMs: 0 }));

    expect(await screen.findByText('Нет оценённых занятий')).toBeInTheDocument();
    expect(screen.getByText('Период UTC:').parentElement).toHaveTextContent('нет данных');
    expect(screen.queryByRole('heading', { name: 'Распределение результатов' })).not.toBeInTheDocument();
  });

  it('separates an analytics API error from an empty summary', async () => {
    renderTeacher(createTeacherMockApi({ failAnalytics: true, delayMs: 0 }));

    const alert = await screen.findByRole('alert', { name: 'Аналитика не загрузилась' });
    expect(alert).toHaveTextContent('Проверьте соединение');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
    expect(screen.queryByText('Нет оценённых занятий')).not.toBeInTheDocument();
  });

  it('selects a scenario, starts and completes a session', async () => {
    const user = userEvent.setup();
    renderTeacher();

    expect(await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Открыть сценарий «ДТП с пострадавшими»' }));
    expect(screen.getByRole('heading', { name: 'ДТП с пострадавшими', level: 2 })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));
    expect(await screen.findByText('ACTIVE')).toBeInTheDocument();
    const scenarioInfo = screen.getByRole('region', { name: 'Информация о сценарии' });
    expect(within(scenarioInfo).getByRole('heading', { name: 'ДТП с пострадавшими' })).toBeInTheDocument();
    expect(within(scenarioInfo).getByText('Дорожное происшествие')).toBeInTheDocument();
    expect(within(scenarioInfo).getByText('Средняя')).toBeInTheDocument();
    expect(within(scenarioInfo).getByText('8 мин')).toBeInTheDocument();
    expect(within(scenarioInfo).queryByText('Версия')).not.toBeInTheDocument();
    expect(screen.getByTestId('session-timer')).toHaveTextContent(/^\d{2}:\d{2}$/);
    expect(screen.getByText('Идентификатор сессии')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Завершить занятие' }));
    expect(await screen.findByText('COMPLETED')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Новое занятие' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Открыть сценарий «Задымление в мусоропроводе»' }));
    expect(within(scenarioInfo).getByRole('heading', { name: 'ДТП с пострадавшими' })).toBeInTheDocument();
    expect(within(scenarioInfo).queryByRole('heading', { name: 'Задымление в мусоропроводе' })).not.toBeInTheDocument();
  });

  it('shows several DDS services with independent statuses and available history', async () => {
    const user = userEvent.setup();
    const services = [
      makeServiceAssignment('MCHS', 'Служба 101 (МЧС)', 'RECEIVED'),
      makeServiceAssignment('MEDICAL', 'Скорая помощь', 'COMPLETED'),
    ];
    renderTeacher(createTeacherMockApi({ delayMs: 0, serviceAssignments: services }));

    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));

    expect(await screen.findByRole('heading', { name: 'Службы ДДС' })).toBeInTheDocument();
    const fireService = screen.getByText('Служба 101 (МЧС)').closest('article');
    const medicalService = screen.getByText('Скорая помощь').closest('article');
    expect(fireService).not.toBeNull();
    expect(medicalService).not.toBeNull();
    expect(within(fireService!).getAllByText('Получена').length).toBeGreaterThan(0);
    expect(within(medicalService!).getAllByText('Завершена').length).toBeGreaterThan(0);
    expect(screen.getAllByText('История статусов (1)')).toHaveLength(2);
  });

  it('refreshes one DDS service from a live event without changing the others', async () => {
    const user = userEvent.setup();
    const base = createTeacherMockApi({ delayMs: 0 });
    let services = [
      makeServiceAssignment('MCHS', 'Служба 101 (МЧС)', 'ADDED'),
      makeServiceAssignment('MEDICAL', 'Скорая помощь', 'ACCEPTED'),
    ];
    const api: TeacherApi = {
      ...base,
      getServiceAssignments: vi.fn(async (sessionId: string) => (
        structuredClone(services.map((item) => ({ ...item, sessionId })))
      )),
    };
    let emitEvent: Parameters<TeacherSessionEvents['subscribe']>[1] | null = null;
    const sessionEvents: TeacherSessionEvents = {
      subscribe(_sessionId, onEvent, onConnectionState) {
        emitEvent = onEvent;
        onConnectionState('connected');
        return () => {};
      },
    };
    renderTeacher(api, sessionEvents);

    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));
    expect(await screen.findByText('Служба 101 (МЧС)')).toBeInTheDocument();

    services = [
      makeServiceAssignment('MCHS', 'Служба 101 (МЧС)', 'RESPONDING'),
      makeServiceAssignment('MEDICAL', 'Скорая помощь', 'ACCEPTED'),
    ];
    await act(async () => {
      emitEvent?.({
        eventId: 'live-event-1',
        sessionId: document.querySelector('.session-id')!.textContent!,
        type: 'service.status_changed',
        timestamp: '2026-09-25T12:01:00.000Z',
        source: 'core',
        payload: {},
      });
    });

    await waitFor(() => {
      const fireService = screen.getByText('Служба 101 (МЧС)').closest('article');
      expect(within(fireService!).getAllByText('Следует к месту').length).toBeGreaterThan(0);
    });
    const medicalService = screen.getByText('Скорая помощь').closest('article');
    expect(within(medicalService!).getAllByText('Принята').length).toBeGreaterThan(0);
  });

  it('uses polling as a fallback and shows the saved score', async () => {
    const user = userEvent.setup();
    const base = createTeacherMockApi({ delayMs: 0 });
    const report: SessionReport = {
      sessionId: 'filled-after-launch',
      score: 84,
      maxScore: 100,
      passed: true,
      criteria: [],
      errors: [],
      recommendations: [],
    };
    let activeReads = 0;
    const getAnalytics = vi.fn()
      .mockResolvedValueOnce(makeAnalytics({ completedSessions: 2 }))
      .mockResolvedValue(makeAnalytics());
    const api: TeacherApi = {
      ...base,
      getAnalytics,
      async getCurrentSession() {
        const current = await base.getCurrentSession();
        if (!current || activeReads++ === 0) return current;
        return {
          ...current,
          state: 'SCORED',
          report: { ...report, sessionId: current.id },
        };
      },
    };
    renderTeacher(api, pollingTeacherSessionEvents, 10);

    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));

    expect(await screen.findByText(/Оценка: 84 из 100/)).toBeInTheDocument();
    expect(screen.getByText('SCORED')).toBeInTheDocument();
    expect(await screen.findByText('Занятий: 3')).toBeInTheDocument();
    expect(getAnalytics).toHaveBeenCalledTimes(2);
  });

  it('filters scenarios by difficulty', async () => {
    const user = userEvent.setup();
    renderTeacher();
    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });

    await user.click(screen.getByRole('radio', { name: 'Высокая' }));
    expect(screen.getByRole('heading', { name: 'Запах газа в подъезде', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сценарий не готов' })).toBeDisabled();
  });

  it('restores the session after a page reload and clears it for a new session', async () => {
    const user = userEvent.setup();
    renderTeacher();
    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));
    await screen.findByText('ACTIVE');
    const sessionId = document.querySelector('.session-id')?.textContent;
    expect(sessionId).toBeTruthy();

    cleanup();
    renderTeacher(createTeacherMockApi({ delayMs: 0 }));
    expect(await screen.findByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText(sessionId!)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Завершить занятие' }));
    await screen.findByText('COMPLETED');
    cleanup();
    renderTeacher(createTeacherMockApi({ delayMs: 0 }));
    expect(await screen.findByText('COMPLETED')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Новое занятие' }));
    expect(await screen.findByRole('button', { name: 'Запустить занятие' })).toBeInTheDocument();
    cleanup();
    renderTeacher(createTeacherMockApi({ delayMs: 0 }));
    expect(await screen.findByRole('button', { name: 'Запустить занятие' })).toBeInTheDocument();
    expect(screen.queryByText('COMPLETED')).not.toBeInTheDocument();
  });

  it('shows an empty state', async () => {
    renderTeacher(createTeacherMockApi({ scenarios: [], delayMs: 0 }));
    expect(await screen.findByText('Сценариев нет')).toBeInTheDocument();
  });

  it('shows an error state and retry action', async () => {
    renderTeacher(createTeacherMockApi({ failScenarios: true, delayMs: 0 }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить сценарии');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});
