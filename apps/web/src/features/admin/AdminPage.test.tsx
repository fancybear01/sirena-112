// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminPage } from './AdminPage';
import type { AuthRole } from '../../api/auth';

type GroupRecord = { id: string; name: string };
type UserRecord = {
  id: string;
  username: string;
  displayName: string;
  role: AuthRole;
  groupId: string | null;
  locked: boolean;
  enabled: boolean;
};

let groups: GroupRecord[];
let users: UserRecord[];
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

beforeAll(() => {
  HTMLElement.prototype.scrollIntoView = () => {};
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
  groups = [
    { id: 'group-1', name: 'Группа 1' },
    { id: 'group-2', name: 'Группа 2' },
  ];
  users = [{
    id: 'teacher-id',
    username: 'teacher',
    displayName: 'Преподаватель',
    role: 'TEACHER',
    groupId: 'group-1',
    locked: false,
    enabled: true,
  }];
  fetchMock = vi.fn<typeof fetch>(async (input, options) => {
    const url = typeof input === 'string' ? input : 'url' in input ? input.url : input.toString();
    const method = options?.method ?? 'GET';
    if (url.endsWith('/api/auth/csrf')) {
      return json({ token: 'csrf-token', headerName: 'X-XSRF-TOKEN' });
    }
    if (url.endsWith('/api/admin/groups') && method === 'GET') return json(groups);
    if (url.endsWith('/api/admin/users') && method === 'GET') return json(users);
    if (url.endsWith('/api/admin/groups') && method === 'POST') {
      const body = JSON.parse(String(options?.body)) as { name: string };
      const group = { id: `group-${groups.length + 1}`, name: body.name.trim() };
      groups = [...groups, group];
      return json(group, 201);
    }
    if (url.endsWith('/api/admin/users') && method === 'POST') {
      const body = JSON.parse(String(options?.body)) as {
        username: string;
        displayName: string;
        role: AuthRole;
        groupId: string | null;
      };
      const user = { id: `user-${users.length + 1}`, ...body, locked: false, enabled: true };
      users = [...users, user];
      return json(user, 201);
    }
    const roleMatch = url.match(/\/api\/admin\/users\/([^/]+)\/role$/);
    if (roleMatch && method === 'PATCH') {
      const body = JSON.parse(String(options?.body)) as { role: AuthRole; groupId: string | null };
      users = users.map((user) => user.id === roleMatch[1] ? { ...user, ...body } : user);
      return json(users.find((user) => user.id === roleMatch[1]));
    }
    const lockMatch = url.match(/\/api\/admin\/users\/([^/]+)\/lock$/);
    if (lockMatch && method === 'PATCH') {
      const body = JSON.parse(String(options?.body)) as { locked: boolean };
      users = users.map((user) => user.id === lockMatch[1] ? { ...user, locked: body.locked } : user);
      return json(users.find((user) => user.id === lockMatch[1]));
    }
    return json({ message: 'Не найдено' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(<MantineProvider><AdminPage /></MantineProvider>);
}

describe('admin user management', () => {
  it('loads users and creates a group and account without exposing stored passwords', async () => {
    renderPage();
    expect(await screen.findByText('teacher')).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Название'), 'Группа 3');
    await userEvent.click(screen.getByRole('button', { name: 'Создать группу' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/groups$/),
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Группа 3' }) }),
    ));

    await userEvent.type(screen.getByLabelText('Логин'), 'student2');
    await userEvent.type(screen.getByLabelText('Имя'), 'Новый студент');
    await userEvent.type(screen.getByLabelText(/^Пароль/), 'student-password-123');
    await userEvent.click(screen.getByRole('button', { name: 'Создать' }));

    expect(await screen.findByText('student2')).toBeInTheDocument();
    expect(screen.queryByText('student-password-123')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Пароль/)).toHaveValue('');
  });

  it('changes role, assigns a group and locks an account through implemented actions', async () => {
    renderPage();
    await screen.findByText('teacher');

    await userEvent.click(screen.getByRole('combobox', { name: 'Группа teacher' }));
    await userEvent.keyboard('{ArrowDown}{Enter}');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/users\/teacher-id\/role$/),
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ role: 'TEACHER', groupId: 'group-2' }) }),
    ));

    await userEvent.click(screen.getByRole('combobox', { name: 'Роль teacher' }));
    await userEvent.keyboard('{ArrowUp}{Enter}');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/users\/teacher-id\/role$/),
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ role: 'ADMIN', groupId: null }) }),
    ));

    await userEvent.click(screen.getByRole('button', { name: 'Заблокировать' }));
    expect(await screen.findByRole('button', { name: 'Разблокировать' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/users\/teacher-id\/lock$/),
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ locked: true }) }),
    );
  });
});
