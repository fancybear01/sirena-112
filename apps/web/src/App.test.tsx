// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { App } from './App';

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

function renderAt(path: string) {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe('frontend routes', () => {
  it.each([
    ['/login', 'Выберите свою роль'],
    ['/admin', 'Платформа под контролем'],
    ['/teacher', 'Обучение в ваших руках'],
    ['/student', 'Практика начинается здесь'],
  ])('renders %s directly', (path, heading) => {
    renderAt(path);
    expect(screen.getByRole('heading', { name: heading, level: 1 })).toBeInTheDocument();
  });

  it.each([
    ['администратор', 'Платформа под контролем', 'admin'],
    ['преподаватель', 'Обучение в ваших руках', 'teacher'],
    ['обучающийся', 'Практика начинается здесь', 'student'],
  ])('mock login opens the %s workspace', async (label, heading, role) => {
    renderAt('/login');
    await userEvent.click(screen.getByRole('button', { name: `Войти как ${label}` }));
    expect(screen.getByRole('heading', { name: heading, level: 1 })).toBeInTheDocument();
    expect(window.localStorage.getItem('sirena-112:mock-role')).toBe(role);
  });

  it('shows a 404 for an unknown path', () => {
    renderAt('/unknown');
    expect(screen.getByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument();
  });
});
