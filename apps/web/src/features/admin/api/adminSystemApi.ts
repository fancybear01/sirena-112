export type ServiceStatus = {
  id: 'core' | 'ai' | 'media' | 'postgres' | 'asterisk';
  label: string;
  status: 'UP' | 'DOWN';
  detail: string;
};

export type ResourceStatus = {
  id: 'cpu' | 'memory' | 'disk';
  label: string;
  usedPercent: number;
  usedBytes?: number;
  totalBytes?: number;
};

export type AdminAction = 'start' | 'stop' | 'restart' | 'update';
export type ManagedService = 'all' | ServiceStatus['id'] | 'web' | 'monitor';

export type AuditEntry = {
  id: string;
  timestamp: string;
  actor: string;
  action: AdminAction;
  service: ManagedService;
  outcome: 'STARTED' | 'OK' | 'FAILED';
  message?: string;
  requestId: string;
};

export type SystemStatus = {
  status: 'UP' | 'DOWN';
  updatedAt: string;
  services: ServiceStatus[];
  resources: ResourceStatus[];
  errors: { component: string; message: string }[];
  lastAction: AuditEntry | null;
};

export type SafeConfiguration = {
  sections: Record<'sip' | 'database' | 'limits' | 'logging', { key: string; label: string; value: string }[]>;
  secrets: { key: string; value: null; note: string }[];
  backup: string[];
  editableInBrowser: false;
};

type Fetch = typeof fetch;

function defaultHelperUrl(): string {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8100';
  const host = window.location.hostname === '::1' ? '[::1]' : window.location.hostname;
  return `${window.location.protocol}//${host}:8100`;
}

async function responseJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null) as { message?: string } | null;
  if (!response.ok) throw new Error(payload?.message ?? `Admin helper вернул ошибку ${response.status}.`);
  return payload as T;
}

export function createAdminSystemApi(baseUrl = defaultHelperUrl(), fetchImpl?: Fetch) {
  const executeFetch = (...args: Parameters<Fetch>) => (fetchImpl ?? globalThis.fetch)(...args);
  const request = async <T>(path: string): Promise<T> => responseJson<T>(await executeFetch(`${baseUrl}${path}`, {
    credentials: 'include', headers: { Accept: 'application/json' },
  }));

  return {
    status: () => request<SystemStatus>('/api/status'),
    configuration: () => request<SafeConfiguration>('/api/configuration'),
    audit: async () => (await request<{ entries: AuditEntry[] }>('/api/audit')).entries,
    action: async (action: AdminAction, service: ManagedService): Promise<AuditEntry> => {
      const csrf = await request<{ token: string; headerName: string }>('/api/csrf');
      return responseJson<AuditEntry>(await executeFetch(`${baseUrl}/api/actions`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', [csrf.headerName]: csrf.token },
        body: JSON.stringify({ action, service, confirmed: true }),
      }));
    },
  };
}

export const adminSystemApi = createAdminSystemApi();
