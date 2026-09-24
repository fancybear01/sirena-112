// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { StudentPage } from './student/StudentPage';
import { createStudentMockApi } from './student/api/studentMockApi';
import { TeacherPage } from './teacher/TeacherPage';
import { createTeacherMockApi } from './teacher/api/teacherMockApi';

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
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

function renderPage(page: React.ReactNode) {
  return render(<MantineProvider>{page}</MantineProvider>);
}

async function selectFirst(user: ReturnType<typeof userEvent.setup>, name: RegExp | string) {
  await user.click(screen.getByRole('combobox', { name }));
  await user.keyboard('{ArrowDown}{Enter}');
}

describe('teacher to student mock flow', () => {
  it('runs scenario 1050602 from teacher launch through the Core-shaped report', async () => {
    const user = userEvent.setup();
    const teacherApi = createTeacherMockApi({ delayMs: 0, storage: window.localStorage });
    renderPage(<TeacherPage api={teacherApi} />);

    await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));
    const sessionId = await screen.findByText(/[0-9a-f]{8}-[0-9a-f-]{27}/i);

    cleanup();
    const studentApi = createStudentMockApi({ delayMs: 0, storage: window.localStorage });
    renderPage(<StudentPage api={studentApi} />);
    expect(await screen.findByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 })).toBeInTheDocument();

    await selectFirst(user, /1\. Группа происшествия/);
    await waitFor(() => expect(screen.getByRole('combobox', { name: /2\. Признак происшествия/ })).toBeEnabled());
    await selectFirst(user, /2\. Признак происшествия/);
    await waitFor(() => expect(screen.getByRole('combobox', { name: /3\. Уточнение признака/ })).toBeEnabled());
    await selectFirst(user, /3\. Уточнение признака/);
    await screen.findByRole('heading', { name: 'Дополнительные вопросы' });

    for (const name of [
      'Объект из перечня', 'Требуется эвакуация', 'Медицинская помощь', 'Нет доступа',
      'Правонарушение', 'Угроза людям', 'Перекрытие движения',
    ]) {
      await user.click(within(screen.getByRole('radiogroup', { name })).getByRole('radio', { name: 'Нет' }));
    }
    await selectFirst(user, 'Пострадавшие / погибшие');
    await user.type(screen.getByLabelText(/Адрес одной строкой/), 'Учебный адрес, дом 1');
    await user.click(within(screen.getByRole('radiogroup', { name: /Есть пострадавшие/ })).getByRole('radio', { name: 'Нет' }));
    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByRole('heading', { name: 'Результат задания', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Оценка 100 из 100')).toBeInTheDocument();
    const restored = await studentApi.getAssignment();
    expect(restored.session.id).toBe(sessionId.textContent);
    expect(restored.session.card.calculation?.classifierCode).toBe('1050602');
    expect(restored.session.endedAt).not.toBeNull();

    cleanup();
    renderPage(<TeacherPage api={createTeacherMockApi({ delayMs: 0, storage: window.localStorage })} />);
    expect(await screen.findByText('SCORED')).toBeInTheDocument();
    expect(screen.getByText(/Оценка: 100 из 100/)).toBeInTheDocument();
    expect(await screen.findByText('Назначено: 14')).toBeInTheDocument();

    cleanup();
    renderPage(<TeacherPage api={createTeacherMockApi({ delayMs: 0, storage: window.localStorage })} />);
    expect(await screen.findByText('SCORED')).toBeInTheDocument();
    expect(screen.getByText(/Оценка: 100 из 100/)).toBeInTheDocument();
  }, 20_000);
});
