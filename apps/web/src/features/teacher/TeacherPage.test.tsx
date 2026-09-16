// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { TeacherPage } from './TeacherPage';
import { createTeacherMockApi } from './api/teacherMockApi';

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

function renderTeacher(api = createTeacherMockApi({ delayMs: 0 })) {
  return render(
    <MantineProvider>
      <TeacherPage api={api} />
    </MantineProvider>,
  );
}

describe('teacher scenario flow', () => {
  it('selects a scenario, starts and completes a session', async () => {
    const user = userEvent.setup();
    renderTeacher();

    expect(await screen.findByRole('heading', { name: 'Пожар в жилом доме', level: 2 })).toBeInTheDocument();
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

    await user.click(screen.getByRole('button', { name: 'Открыть сценарий «Пожар в жилом доме»' }));
    expect(within(scenarioInfo).getByRole('heading', { name: 'ДТП с пострадавшими' })).toBeInTheDocument();
    expect(within(scenarioInfo).queryByRole('heading', { name: 'Пожар в жилом доме' })).not.toBeInTheDocument();
  });

  it('filters scenarios by difficulty', async () => {
    const user = userEvent.setup();
    renderTeacher();
    await screen.findByRole('heading', { name: 'Пожар в жилом доме', level: 2 });

    await user.click(screen.getByRole('radio', { name: 'Высокая' }));
    expect(screen.getByRole('heading', { name: 'Запах газа в подъезде', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сценарий не готов' })).toBeDisabled();
  });

  it('restores the session after a page reload and clears it for a new session', async () => {
    const user = userEvent.setup();
    renderTeacher();
    await screen.findByRole('heading', { name: 'Пожар в жилом доме', level: 2 });
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
