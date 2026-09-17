// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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

describe('teacher to student mock flow', () => {
  it('uses the teacher session for the student assignment and produces its report', async () => {
    const user = userEvent.setup();
    const teacherApi = createTeacherMockApi({ delayMs: 0, storage: window.localStorage });
    renderPage(<TeacherPage api={teacherApi} />);

    await screen.findByRole('heading', { name: 'Пожар в жилом доме', level: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить занятие' }));
    const sessionId = await screen.findByText(/[0-9a-f]{8}-[0-9a-f-]{27}/i);

    cleanup();
    const studentApi = createStudentMockApi({ delayMs: 0, storage: window.localStorage });
    renderPage(<StudentPage api={studentApi} />);
    expect(await screen.findByRole('heading', { name: 'Пожар в жилом доме', level: 2 })).toBeInTheDocument();

    await user.click(screen.getByRole('combobox', { name: /Тип происшествия/ }));
    await user.keyboard('{ArrowDown}{Enter}');
    await user.type(screen.getByLabelText(/Адрес/), 'ул. Лесная, д. 14');
    await user.type(
      screen.getByLabelText(/Описание/),
      'Густой дым на лестничной площадке, на пятом этаже могут оставаться люди.',
    );
    await user.click(screen.getByRole('checkbox', { name: 'Пожарная охрана' }));
    await user.click(screen.getByRole('checkbox', { name: 'Скорая помощь' }));
    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByRole('heading', { name: 'Результат задания', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Оценка 100 из 100')).toBeInTheDocument();
    expect((await studentApi.getAssignment()).session.id).toBe(sessionId.textContent);
  }, 10_000);
});
