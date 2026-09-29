// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminSystemPanel } from './AdminSystemPanel';

let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
let healthy: boolean;

const configuration = {
  sections: { sip: [], database: [], limits: [], logging: [] },
  secrets: [],
  backup: ['Создайте дамп.', 'Храните отдельно.', 'Проверьте health.'],
  editableInBrowser: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function systemStatus() {
  return {
    status: healthy ? 'UP' : 'DOWN',
    updatedAt: '2026-09-29T09:00:00Z',
    services: [{ id: 'core', label: 'Core', status: healthy ? 'UP' : 'DOWN',
      detail: healthy ? 'Готов к работе' : 'Connection refused' }],
    resources: [{ id: 'cpu', label: 'CPU', usedPercent: 24.5 }],
    errors: healthy ? [] : [{ component: 'core', message: 'Connection refused' }],
    lastAction: null,
  };
}

beforeAll(() => {
  HTMLElement.prototype.scrollIntoView = () => {};
  globalThis.ResizeObserver = class implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false,
  });
});

beforeEach(() => {
  healthy = false;
  fetchMock = vi.fn<typeof fetch>(async (input, options) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith('/api/status')) return json(systemStatus());
    if (url.endsWith('/api/configuration')) return json(configuration);
    if (url.endsWith('/api/audit')) return json({ entries: [] });
    if (url.endsWith('/api/csrf')) return json({ token: 'helper-csrf', headerName: 'X-Admin-CSRF' });
    if (url.endsWith('/api/actions') && options?.method === 'POST') return json({
      id: 'audit-1', timestamp: '2026-09-29T09:01:00Z', actor: 'admin', action: 'restart',
      service: 'core', outcome: 'OK', requestId: 'request-1',
    });
    return json({ message: 'Не найдено' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPanel() {
  return render(<MantineProvider><AdminSystemPanel /></MantineProvider>);
}

describe('admin system panel', () => {
  it('shows a health failure and replaces it after a manual refresh', async () => {
    renderPanel();
    expect((await screen.findAllByText('Connection refused')).length).toBeGreaterThan(0);
    expect(screen.getByText('Есть сбой')).toBeInTheDocument();

    healthy = true;
    await userEvent.click(screen.getByRole('button', { name: 'Обновить состояние' }));

    expect(await screen.findByText('Комплекс готов')).toBeInTheDocument();
    expect(screen.queryByText('Connection refused')).not.toBeInTheDocument();
  });

  it('requires confirmation and sends only an allowlisted action and service', async () => {
    renderPanel();
    await screen.findAllByText('Connection refused');

    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить Core' }));
    expect(await screen.findByText(/Перезапустить: Core/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/actions$/),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ action: 'restart', service: 'core', confirmed: true }),
        headers: expect.objectContaining({ 'X-Admin-CSRF': 'helper-csrf' }),
      }),
    ));
  });
});
