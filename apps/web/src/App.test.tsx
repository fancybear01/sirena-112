// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthRole, CurrentUser } from './api/auth';
import { createHttpClient } from './api/httpClient';
import {
  apiTeacherSessionStorageKey,
  studentDraftStorageKey,
  teacherSessionStorageKey,
} from './api/mockStorage';

const users: Record<AuthRole, CurrentUser> = {
  ADMIN: { id: 'admin-id', username: 'admin', displayName: 'Администратор', role: 'ADMIN', groupId: null },
  TEACHER: { id: 'teacher-id', username: 'teacher', displayName: 'Преподаватель', role: 'TEACHER', groupId: 'group-1' },
  STUDENT: { id: 'student-id', username: 'student', displayName: 'Обучающийся', role: 'STUDENT', groupId: 'group-1' },
};

const headings: Record<AuthRole, string> = {
  ADMIN: 'Контроль локального комплекса',
  TEACHER: 'Сценарии',
  STUDENT: 'Моё задание',
};

let currentUser: CurrentUser | null;
let loginUser: CurrentUser;
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

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

beforeEach(() => {
  currentUser = null;
  loginUser = users.ADMIN;
  fetchMock = vi.fn<typeof fetch>(async (input, options) => {
    const url = typeof input === 'string' ? input : 'url' in input ? input.url : input.toString();
    if (url.endsWith('/api/auth/me')) {
      return currentUser ? json(currentUser) : json({ message: 'Требуется вход' }, 401);
    }
    if (url.endsWith('/api/auth/csrf')) {
      return json({ token: 'csrf-token', headerName: 'X-XSRF-TOKEN' });
    }
    if (url.endsWith('/api/auth/login') && options?.method === 'POST') {
      currentUser = loginUser;
      return json(loginUser);
    }
    if (url.endsWith('/api/auth/logout') && options?.method === 'POST') {
      currentUser = null;
      return new Response(null, { status: 204 });
    }
    if (url.endsWith('/api/admin/groups')) return json([{ id: 'group-1', name: 'Группа 1' }]);
    if (url.endsWith('/api/admin/users')) return json([users.ADMIN]);
    return json({ message: 'Не найдено' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe('authenticated routes', () => {
  it('shows the Core login form instead of demo role buttons', async () => {
    renderAt('/login');
    expect(await screen.findByRole('heading', { name: 'Вход в систему', level: 1 })).toBeInTheDocument();
    expect(screen.queryByText('Демо-вход без пароля')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Логин/)).toBeEnabled();
  });

  it.each<AuthRole>(['ADMIN', 'TEACHER', 'STUDENT'])(
    'logs a %s account into its own workspace',
    async (role) => {
      loginUser = users[role];
      renderAt('/login');
      await screen.findByLabelText(/^Логин/);
      await userEvent.type(screen.getByLabelText(/^Логин/), loginUser.username);
      await userEvent.type(screen.getByLabelText(/^Пароль/), 'password-for-tests');
      await userEvent.click(screen.getByRole('button', { name: 'Войти' }));

      expect(await screen.findByRole('heading', { name: headings[role], level: 1 })).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/auth\/login$/), expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }));
    },
  );

  it.each([
    ['ADMIN', '/student', headings.ADMIN],
    ['TEACHER', '/admin', headings.TEACHER],
    ['STUDENT', '/teacher', headings.STUDENT],
  ] as const)('redirects %s away from a foreign direct URL', async (role, path, ownHeading) => {
    currentUser = users[role];
    renderAt(path);
    expect(await screen.findByRole('heading', { name: ownHeading, level: 1 })).toBeInTheDocument();
  });

  it('restores an authenticated route after reload through /api/auth/me', async () => {
    currentUser = users.TEACHER;
    renderAt('/teacher');
    expect(await screen.findByRole('heading', { name: headings.TEACHER, level: 1 })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/auth\/me$/), expect.objectContaining({
      credentials: 'include',
    }));
  });

  it('returns an anonymous visitor from a protected route to login', async () => {
    renderAt('/admin');
    expect(await screen.findByRole('heading', { name: 'Вход в систему', level: 1 })).toBeInTheDocument();
  });

  it('logs out through Core and clears private cached state', async () => {
    currentUser = users.STUDENT;
    window.localStorage.setItem(studentDraftStorageKey, '{"secret":"draft"}');
    window.localStorage.setItem(apiTeacherSessionStorageKey, '{"secret":"session"}');
    renderAt('/student');
    await screen.findByRole('heading', { name: headings.STUDENT, level: 1 });
    await userEvent.click(screen.getByRole('button', { name: 'Выйти' }));

    expect(await screen.findByRole('heading', { name: 'Вход в систему', level: 1 })).toBeInTheDocument();
    expect(window.localStorage.getItem(studentDraftStorageKey)).toBeNull();
    expect(window.localStorage.getItem(apiTeacherSessionStorageKey)).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/auth\/logout$/), expect.objectContaining({
      method: 'POST',
    }));
  });

  it('drops an expired session immediately and removes another user cache', async () => {
    currentUser = users.TEACHER;
    window.localStorage.setItem(teacherSessionStorageKey, '{"secret":"teacher-state"}');
    renderAt('/teacher');
    await screen.findByRole('heading', { name: headings.TEACHER, level: 1 });

    currentUser = null;
    await act(async () => {
      await expect(createHttpClient('').request('/api/auth/me')).rejects.toMatchObject({ status: 401 });
    });

    expect(await screen.findByRole('heading', { name: 'Вход в систему', level: 1 })).toBeInTheDocument();
    expect(window.localStorage.getItem(teacherSessionStorageKey)).toBeNull();
  });

  it('shows a 404 for an unknown path', () => {
    renderAt('/unknown');
    expect(screen.getByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument();
  });
});
