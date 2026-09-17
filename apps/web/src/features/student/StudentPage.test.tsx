// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { StudentPage } from './StudentPage';
import { createStudentMockApi } from './api/studentMockApi';

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

function renderStudent(api = createStudentMockApi({ delayMs: 0, storage: null })) {
  return render(
    <MantineProvider>
      <StudentPage api={api} />
    </MantineProvider>,
  );
}

async function fillValidCard(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('combobox', { name: /Тип происшествия/ }));
  await user.keyboard('{ArrowDown}{Enter}');
  await user.type(screen.getByLabelText(/Адрес/), 'ул. Лесная, д. 14');
  await user.type(
    screen.getByLabelText(/Описание/),
    'Густой дым на лестничной площадке, на пятом этаже могут оставаться люди.',
  );
  await user.click(screen.getByRole('checkbox', { name: 'Пожарная охрана' }));
  await user.click(screen.getByRole('checkbox', { name: 'Скорая помощь' }));
}

describe('student assignment flow', () => {
  it('shows the assigned scenario and timer without category, difficulty or idle save hint', async () => {
    renderStudent();
    expect(await screen.findByRole('heading', { name: 'Моё задание', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Пожар в жилом доме', level: 2 })).toBeInTheDocument();
    const assignmentBrief = document.querySelector<HTMLElement>('.assignment-brief');
    expect(assignmentBrief).not.toBeNull();
    expect(within(assignmentBrief!).queryByText('Пожар')).not.toBeInTheDocument();
    expect(within(assignmentBrief!).queryByText('Базовый уровень')).not.toBeInTheDocument();
    expect(screen.queryByText('Изменения сохраняются автоматически')).not.toBeInTheDocument();
    expect(screen.getByTestId('assignment-timer')).toHaveTextContent(/^\d{2}:\d{2}$/);
  });

  it('does not submit an empty card and shows field validation', async () => {
    const user = userEvent.setup();
    const api = createStudentMockApi({ delayMs: 0, storage: null });
    const submit = vi.spyOn(api, 'submitCard');
    renderStudent(api);
    await screen.findByRole('heading', { name: 'Карточка происшествия' });

    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText('Заполните обязательные поля перед отправкой карточки.')).toBeInTheDocument();
    expect(screen.getByText('Выберите тип происшествия.')).toBeInTheDocument();
    expect(screen.getByText('Укажите адрес происшествия.')).toBeInTheDocument();
    expect(screen.getByText('Опишите обстоятельства происшествия.')).toBeInTheDocument();
    expect(screen.getByText('Выберите хотя бы одну необходимую службу.')).toBeInTheDocument();
  });

  it('submits a completed card and displays an explainable score', async () => {
    const user = userEvent.setup();
    renderStudent();
    await screen.findByRole('heading', { name: 'Карточка происшествия' });
    await fillValidCard(user);

    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByRole('heading', { name: 'Результат задания', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Оценка 100 из 100')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Выполненные критерии' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Ошибки' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Рекомендации' })).toBeInTheDocument();
  });

  it('restores a locally saved draft after remounting', async () => {
    const user = userEvent.setup();
    renderStudent(createStudentMockApi({ delayMs: 0, storage: window.localStorage }));
    const address = await screen.findByLabelText(/Адрес/);
    await user.type(address, 'ул. Лесная, д. 14');
    await waitFor(() => expect(screen.getByText('Черновик сохранён локально')).toBeInTheDocument());

    cleanup();
    renderStudent(createStudentMockApi({ delayMs: 0, storage: window.localStorage }));
    expect(await screen.findByLabelText(/Адрес/)).toHaveValue('ул. Лесная, д. 14');
  });

  it('shows loading errors with a retry action', async () => {
    renderStudent(createStudentMockApi({ delayMs: 0, failLoad: true, storage: null }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить задание');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('keeps the form available when submission fails', async () => {
    const user = userEvent.setup();
    renderStudent(createStudentMockApi({ delayMs: 0, failSubmit: true, storage: null }));
    await screen.findByRole('heading', { name: 'Карточка происшествия' });
    await fillValidCard(user);
    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByText('Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отправить на оценку' })).toBeInTheDocument();
  });
});
