// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import type { ServiceAssignment } from '../../api/types';
import type { StudentApi } from './api/types';
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
  return render(<MantineProvider><StudentPage api={api} /></MantineProvider>);
}

function createOverdueAssignment(): ServiceAssignment {
  const timestamp = '2026-09-23T10:00:00.000Z';
  return {
    id: '10000000-0000-4000-8000-000000000001',
    sessionId: 'a13e08ea-220f-458a-95f6-95b7c3a3f14c',
    serviceId: 'MCHS',
    displayName: 'Служба 101 (МЧС)',
    cardRevision: 10,
    status: 'ADDED',
    createdAt: timestamp,
    updatedAt: timestamp,
    deadlineAt: timestamp,
    overdue: true,
    history: [{
      eventId: '20000000-0000-4000-8000-000000000001',
      sequence: 1,
      fromStatus: null,
      status: 'ADDED',
      timestamp,
      source: 'SYSTEM',
      comment: null,
      refusalReason: null,
    }],
  };
}

async function selectFirstOption(user: ReturnType<typeof userEvent.setup>, name: RegExp | string) {
  const select = screen.getByRole('combobox', { name });
  await user.click(select);
  await user.keyboard('{ArrowDown}{Enter}');
}

async function chooseReferenceSigns(user: ReturnType<typeof userEvent.setup>) {
  await selectFirstOption(user, /1\. Группа происшествия/);
  await waitFor(() => expect(screen.getByRole('combobox', { name: /2\. Признак происшествия/ })).toBeEnabled());
  await selectFirstOption(user, /2\. Признак происшествия/);
  await waitFor(() => expect(screen.getByRole('combobox', { name: /3\. Уточнение признака/ })).toBeEnabled());
  await selectFirstOption(user, /3\. Уточнение признака/);
  await screen.findByRole('heading', { name: 'Дополнительные вопросы' });
}

async function answerReferenceQuestions(user: ReturnType<typeof userEvent.setup>) {
  const yesNoQuestions = [
    'Объект из перечня',
    'Требуется эвакуация',
    'Медицинская помощь',
    'Нет доступа',
    'Правонарушение',
    'Угроза людям',
    'Перекрытие движения',
  ];
  for (const name of yesNoQuestions) {
    const group = screen.getByRole('radiogroup', { name });
    await user.click(within(group).getByRole('radio', { name: 'Нет' }));
  }
  await selectFirstOption(user, 'Пострадавшие / погибшие');
}

async function fillValidCard(user: ReturnType<typeof userEvent.setup>) {
  await chooseReferenceSigns(user);
  await answerReferenceQuestions(user);
  await user.type(screen.getByLabelText('Описание со слов заявителя'), 'Дым идёт из мусоропровода на первом этаже.');
  await user.type(screen.getByLabelText(/Адрес одной строкой/), 'Учебный адрес, дом 1');
  const victims = screen.getByRole('radiogroup', { name: /Есть пострадавшие/ });
  await user.click(within(victims).getByRole('radio', { name: 'Нет' }));
}

describe('student assignment flow', () => {
  it('shows scenario 1050602, a timer and no editable computed fields', async () => {
    renderStudent();
    expect(await screen.findByRole('heading', { name: 'Моё задание', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Задымление в мусоропроводе', level: 2 })).toBeInTheDocument();
    expect(screen.getByText(/классификатор 046-2024-11-15/i)).toBeInTheDocument();
    expect(screen.getByTestId('assignment-timer')).toHaveTextContent(/^\+?\d{2}:\d{2}$/);
    expect(screen.queryByLabelText('Тип происшествия')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Необходимые службы')).not.toBeInTheDocument();
  });

  it('requests the next sign level and dependent questions step by step', async () => {
    const user = userEvent.setup();
    renderStudent();
    await screen.findByRole('heading', { name: 'Карточка происшествия' });
    expect(screen.getByRole('combobox', { name: /2\. Признак происшествия/ })).toBeDisabled();
    expect(screen.queryByRole('heading', { name: 'Дополнительные вопросы' })).not.toBeInTheDocument();

    await selectFirstOption(user, /1\. Группа происшествия/);
    await waitFor(() => expect(screen.getByRole('combobox', { name: /2\. Признак происшествия/ })).toBeEnabled());
    expect(await screen.findByRole('heading', { name: 'Дополнительные вопросы' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /3\. Уточнение признака/ })).toBeDisabled();

    await selectFirstOption(user, /2\. Признак происшествия/);
    await waitFor(() => expect(screen.getByRole('combobox', { name: /3\. Уточнение признака/ })).toBeEnabled());
    await selectFirstOption(user, /3\. Уточнение признака/);

    expect(screen.getByRole('radiogroup', { name: 'Нет доступа' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('задымление: мусоропровод')).toBeInTheDocument());
    const dispatchStrip = screen.getByLabelText('Рассчитанные службы ДДС');
    expect(within(dispatchStrip).getByLabelText('Служба 101 (МЧС): рассчитана Core')).toBeInTheDocument();
  }, 10_000);

  it('keeps dependent answers in the existing autosave payload', async () => {
    const user = userEvent.setup();
    const api = createStudentMockApi({ delayMs: 0, storage: null });
    const saveCard = vi.spyOn(api, 'saveCard');
    renderStudent(api);
    await screen.findByRole('heading', { name: 'Карточка происшествия' });

    await selectFirstOption(user, /1\. Группа происшествия/);
    const question = await screen.findByRole('radiogroup', { name: 'Нет доступа' });
    await user.click(within(question).getByRole('radio', { name: 'Нет' }));

    await waitFor(() => expect(saveCard.mock.calls.some(([, savedInput]) => (
      savedInput.incident?.answers.some((answer) => (
        answer.questionId === 'routing.no-access' && answer.optionIds?.[0] === 'NO'
      ))
    ))).toBe(true));
  });

  it('renders radio, checkbox, select and text questions from the form contract', async () => {
    const base = createStudentMockApi({ delayMs: 0, storage: null });
    const api: StudentApi = {
      ...base,
      getCardForm: async () => ({
        classifierVersion: 'test',
        signGroups: [],
        questions: [
          { id: 'radio', label: 'Один вариант', inputType: 'SINGLE_SELECT', required: true, options: [{ id: 'Y', label: 'Да' }, { id: 'N', label: 'Нет' }] },
          { id: 'select', label: 'Выбор из списка', inputType: 'SINGLE_SELECT', required: true, options: [{ id: 'A', label: 'А' }, { id: 'B', label: 'Б' }, { id: 'C', label: 'В' }] },
          { id: 'multi', label: 'Несколько вариантов', inputType: 'MULTI_SELECT', required: true, options: [{ id: 'M', label: 'Вариант М' }] },
          { id: 'text', label: 'Свободный ответ', inputType: 'TEXT', required: true, options: [] },
        ],
      }),
    };
    renderStudent(api);
    expect(await screen.findByRole('radiogroup', { name: 'Один вариант' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Выбор из списка/ })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Вариант М' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Свободный ответ/)).toBeInTheDocument();
  });

  it('removes an empty answer instead of sending an invalid QuestionAnswer to Core', async () => {
    const user = userEvent.setup();
    const base = createStudentMockApi({ delayMs: 0, storage: null });
    const saveCard = vi.spyOn(base, 'saveCard');
    const api: StudentApi = {
      ...base,
      getCardForm: async () => ({
        classifierVersion: 'test',
        signGroups: [],
        questions: [{
          id: 'multi',
          label: 'Дополнительный признак',
          inputType: 'MULTI_SELECT',
          required: false,
          options: [{ id: 'M', label: 'Вариант М' }],
        }],
      }),
    };
    renderStudent(api);
    const address = await screen.findByLabelText(/Адрес одной строкой/);
    await user.type(address, 'Учебный адрес');
    const option = screen.getByRole('checkbox', { name: 'Вариант М' });
    await user.click(option);
    await user.click(option);

    await waitFor(() => expect(saveCard).toHaveBeenCalled());
    const latestInput = saveCard.mock.calls.at(-1)?.[1];
    expect(latestInput?.incident?.answers).toEqual([]);
    expect(screen.queryByText('Не удалось сохранить черновик.')).not.toBeInTheDocument();
  });

  it('validates only source fields required by the card contract', async () => {
    const user = userEvent.setup();
    const api = createStudentMockApi({ delayMs: 0, storage: null });
    const submit = vi.spyOn(api, 'submitCard');
    renderStudent(api);
    await screen.findByRole('heading', { name: 'Карточка происшествия' });

    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText('Заполните обязательные поля перед отправкой карточки.')).toBeInTheDocument();
    expect(screen.getByText('Укажите адрес происшествия.')).toBeInTheDocument();
    expect(screen.getByText('Укажите, есть ли пострадавшие.')).toBeInTheDocument();
    expect(screen.getByText('Выберите признак этого уровня.')).toBeInTheDocument();
  });

  it('submits scenario 1050602 and displays read-only Core service statuses', async () => {
    const user = userEvent.setup();
    const base = createStudentMockApi({ delayMs: 0, storage: null });
    const getServiceAssignments = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([createOverdueAssignment()]);
    renderStudent({ ...base, getServiceAssignments });
    await screen.findByRole('heading', { name: 'Карточка происшествия' });
    await fillValidCard(user);
    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByRole('heading', { name: 'Результат задания', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Оценка 100 из 100')).toBeInTheDocument();
    expect(screen.getByText('Итоговая оценка и рекомендации получены от Core/AI.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Карточка происшествия' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Адрес одной строкой/)).toBeDisabled();
    const dispatchStrip = screen.getByLabelText('Рассчитанные службы ДДС');
    expect(within(dispatchStrip).getByText('Отправлено')).toBeInTheDocument();
    expect(within(dispatchStrip).getByLabelText('Служба 101 (МЧС): Нет реагирования')).toBeInTheDocument();
    expect(within(dispatchStrip).queryByRole('button', { name: 'Отправить на оценку' })).not.toBeInTheDocument();
  }, 15_000);

  it('restores source input from the saved draft after remounting', async () => {
    const user = userEvent.setup();
    renderStudent(createStudentMockApi({ delayMs: 0, storage: window.localStorage }));
    const address = await screen.findByLabelText(/Адрес одной строкой/);
    await user.type(address, 'Учебный адрес, дом 1');
    await waitFor(() => expect(screen.getByText('Черновик сохранён')).toBeInTheDocument());

    cleanup();
    renderStudent(createStudentMockApi({ delayMs: 0, storage: window.localStorage }));
    expect(await screen.findByLabelText(/Адрес одной строкой/)).toHaveValue('Учебный адрес, дом 1');
  });

  it('keeps entered input visible when Core save fails', async () => {
    const user = userEvent.setup();
    renderStudent(createStudentMockApi({ delayMs: 0, failSave: true, storage: null }));
    const address = await screen.findByLabelText(/Адрес одной строкой/);
    await user.type(address, 'Адрес не должен исчезнуть');
    expect(address).toHaveValue('Адрес не должен исчезнуть');
    expect(await screen.findByText('Не удалось сохранить черновик.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Адрес одной строкой/)).toHaveValue('Адрес не должен исчезнуть');
  });

  it('shows loading errors with a retry action', async () => {
    renderStudent(createStudentMockApi({ delayMs: 0, failLoad: true, storage: null }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить задание');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('keeps the completed form available when submission fails', async () => {
    const user = userEvent.setup();
    renderStudent(createStudentMockApi({ delayMs: 0, failSubmit: true, storage: null }));
    await screen.findByRole('heading', { name: 'Карточка происшествия' });
    await fillValidCard(user);
    await user.click(screen.getByRole('button', { name: 'Отправить на оценку' }));

    expect(await screen.findByText('Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Адрес одной строкой/)).toHaveValue('Учебный адрес, дом 1');
    expect(within(screen.getByLabelText('Рассчитанные службы ДДС')).getByText('Ошибка')).toBeInTheDocument();
  }, 15_000);

  it('shows overtime instead of freezing the timer at zero', async () => {
    window.localStorage.setItem('sirena-112:teacher-session', JSON.stringify({
      id: 'a13e08ea-220f-458a-95f6-95b7c3a3f14c',
      scenarioId: '80c14c89-f2b7-527a-bd6f-268cdc3d4a11',
      mode: 'CARD',
      state: 'ACTIVE',
      card: { input: {}, calculation: null },
      cardRevision: 0,
      report: null,
      startedAt: new Date(Date.now() - 35_000).toISOString(),
      endedAt: null,
      timeLimitSeconds: 30,
      timeLimitExceeded: true,
    }));
    renderStudent(createStudentMockApi({ delayMs: 0, storage: window.localStorage }));
    expect(await screen.findByText('Превышение')).toBeInTheDocument();
    expect(screen.getByTestId('assignment-timer')).toHaveTextContent(/^\+00:0[5-9]$/);
  });
});
