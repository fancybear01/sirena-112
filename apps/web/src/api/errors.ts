type ApiErrorOptions = {
  status?: number;
  code?: string;
  details?: unknown;
  cause?: unknown;
};

export class ApiError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message, { cause: options.cause });
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
  }
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401) return 'Сессия авторизации истекла. Войдите снова.';
  if (error.status === 403) return 'Недостаточно прав для выполнения операции.';
  if (error.status === 404) return 'Запрошенные данные не найдены.';
  if (error.status === 409) return 'Состояние данных изменилось. Обновите страницу и повторите попытку.';
  if (error.status !== undefined && error.status >= 500) {
    return 'Core API временно недоступен. Попробуйте ещё раз.';
  }
  return error.message || fallback;
}
