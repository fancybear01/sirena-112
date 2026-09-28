import { describe, expect, it, vi } from 'vitest';
import { resolveApiConfig } from './config';
import { ApiError, getApiErrorMessage } from './errors';
import { createHttpClient } from './httpClient';

describe('API configuration', () => {
  it('uses mock mode and the contract server by default', () => {
    expect(resolveApiConfig({})).toEqual({
      mode: 'mock',
      baseUrl: 'http://localhost:8080',
    });
  });

  it('reads API mode and normalizes a configured base URL', () => {
    expect(resolveApiConfig({
      VITE_API_MODE: ' API ',
      VITE_API_BASE_URL: 'https://core.example.test/',
    })).toEqual({
      mode: 'api',
      baseUrl: 'https://core.example.test',
    });
  });

  it('uses the same-origin proxy in API mode when no URL is configured', () => {
    expect(resolveApiConfig({ VITE_API_MODE: 'api' })).toEqual({ mode: 'api', baseUrl: '' });
  });
});

describe('HTTP client', () => {
  it('serializes JSON requests and returns the response payload', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ token: 'csrf-token', headerName: 'X-XSRF-TOKEN' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ id: 'session-id' }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      ));
    const client = createHttpClient('https://core.example.test', fetchMock);

    await expect(client.request('/api/teacher/sessions', {
      method: 'POST',
      body: { scenarioId: 'scenario-id' },
    })).resolves.toEqual({ id: 'session-id' });
    expect(fetchMock).toHaveBeenNthCalledWith(1,
      'https://core.example.test/api/auth/csrf',
      { credentials: 'include' },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      'https://core.example.test/api/teacher/sessions',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ scenarioId: 'scenario-id' }),
        credentials: 'include',
      }),
    );
    const request = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(request?.headers).get('X-XSRF-TOKEN')).toBe('csrf-token');
  });

  it('converts non-success responses to the shared API error', async () => {
    const client = createHttpClient('https://core.example.test', vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ code: 'SESSION_STATE', message: 'Сессия уже завершена.' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      }),
    ));

    await expect(client.request('/api/session')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'SESSION_STATE',
    });
    expect(getApiErrorMessage(new ApiError('Conflict', { status: 409 }), 'fallback'))
      .toContain('Состояние данных изменилось');
  });
});
