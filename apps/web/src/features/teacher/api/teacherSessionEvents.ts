import { normalizeSessionEvent } from '../../../api/adapters';
import type { ApiConfig } from '../../../api/config';
import type {
  TeacherLiveConnectionState,
  TeacherSessionEvents,
} from './types';

type SessionSocket = {
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
};

type SessionEventOptions = {
  createSocket?: (url: string) => SessionSocket;
  reconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
};

function websocketUrl(baseUrl: string, sessionId: string, afterEventId?: string) {
  const origin = baseUrl || window.location.origin;
  const url = new URL(`/ws/sessions/${encodeURIComponent(sessionId)}/events`, origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  if (afterEventId) url.searchParams.set('afterEventId', afterEventId);
  return url.toString();
}

function emitState(
  callback: (state: TeacherLiveConnectionState) => void,
  state: TeacherLiveConnectionState,
) {
  callback(state);
}

export function createTeacherSessionEvents(
  config: Pick<ApiConfig, 'baseUrl'>,
  options: SessionEventOptions = {},
): TeacherSessionEvents {
  const createSocket = options.createSocket
    ?? ((url: string) => new WebSocket(url) as unknown as SessionSocket);
  const baseDelay = options.reconnectDelayMs ?? 1000;
  const maxDelay = options.maxReconnectDelayMs ?? 10_000;

  return {
    subscribe(sessionId, onEvent, onConnectionState) {
      const seenEventIds = new Set<string>();
      let stopped = false;
      let reconnectAttempt = 0;
      let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
      let socket: SessionSocket | null = null;
      let lastEventId: string | undefined;

      const scheduleReconnect = () => {
        if (stopped || reconnectTimer !== null) return;
        emitState(onConnectionState, 'reconnecting');
        const delay = Math.min(baseDelay * (2 ** reconnectAttempt), maxDelay);
        reconnectAttempt += 1;
        reconnectTimer = globalThis.setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, delay);
      };

      const connect = () => {
        if (stopped) return;
        let disconnected = false;
        const handleDisconnect = () => {
          if (disconnected) return;
          disconnected = true;
          scheduleReconnect();
        };
        try {
          const connectedSocket = createSocket(websocketUrl(config.baseUrl, sessionId, lastEventId));
          socket = connectedSocket;
          connectedSocket.onopen = () => {
            reconnectAttempt = 0;
            emitState(onConnectionState, 'connected');
          };
          connectedSocket.onmessage = ({ data }) => {
            if (typeof data !== 'string') return;
            try {
              const event = normalizeSessionEvent(JSON.parse(data));
              if (event.sessionId !== sessionId || seenEventIds.has(event.eventId)) return;
              seenEventIds.add(event.eventId);
              lastEventId = event.eventId;
              onEvent(event);
            } catch {
              // Ignore a malformed envelope and keep the live connection usable.
            }
          };
          connectedSocket.onclose = handleDisconnect;
          connectedSocket.onerror = () => {
            connectedSocket.close();
            handleDisconnect();
          };
        } catch {
          handleDisconnect();
        }
      };

      emitState(onConnectionState, 'connecting');
      connect();

      return () => {
        stopped = true;
        if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer);
        reconnectTimer = null;
        socket?.close();
        socket = null;
      };
    },
  };
}

export const pollingTeacherSessionEvents: TeacherSessionEvents = {
  subscribe(_sessionId, _onEvent, onConnectionState) {
    emitState(onConnectionState, 'polling');
    return () => {};
  },
};
