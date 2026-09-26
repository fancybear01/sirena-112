import { ApiError } from './errors';

type ErrorPayload = {
  message?: string;
  code?: string;
  [key: string]: unknown;
};

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
};

export type HttpClient = {
  request<T>(path: string, options?: RequestOptions): Promise<T>;
};

function isErrorPayload(value: unknown): value is ErrorPayload {
  return Boolean(value && typeof value === 'object');
}

export function createHttpClient(baseUrl: string, fetchImpl: typeof fetch = fetch): HttpClient {
  return {
    async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
      const headers = new Headers(options.headers);
      headers.set('Accept', 'application/json');
      if (options.body !== undefined) headers.set('Content-Type', 'application/json');
      if (import.meta.env.VITE_AUTH_MODE === 'secure' &&
          options.method && !['GET', 'HEAD', 'OPTIONS'].includes(options.method.toUpperCase())) {
        const csrfResponse = await fetchImpl(`${baseUrl}/api/auth/csrf`, { credentials: 'include' });
        if (!csrfResponse.ok) throw new ApiError('Не удалось получить защитный токен.', { status: csrfResponse.status });
        const csrf = await csrfResponse.json() as { token: string; headerName: string };
        headers.set(csrf.headerName, csrf.token);
      }

      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}${path}`, {
          ...options,
          credentials: 'include',
          headers,
          body: options.body === undefined ? undefined : JSON.stringify(options.body),
        });
      } catch (cause) {
        throw new ApiError('Не удалось подключиться к Core API.', { cause });
      }

      const contentType = response.headers.get('content-type') ?? '';
      const payload: unknown = contentType.includes('application/json')
        ? await response.json().catch(() => null)
        : await response.text().catch(() => '');

      if (!response.ok) {
        const errorPayload = isErrorPayload(payload) ? payload : undefined;
        throw new ApiError(
          typeof errorPayload?.message === 'string'
            ? errorPayload.message
            : `Core API вернул ошибку ${response.status}.`,
          {
            status: response.status,
            code: typeof errorPayload?.code === 'string' ? errorPayload.code : undefined,
            details: payload,
          },
        );
      }

      return payload as T;
    },
  };
}
