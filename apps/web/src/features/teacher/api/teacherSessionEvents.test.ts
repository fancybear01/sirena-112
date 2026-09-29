import { afterEach, describe, expect, it, vi } from 'vitest';
import { createTeacherSessionEvents } from './teacherSessionEvents';

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  close() {
    this.closed = true;
    this.onclose?.();
  }

  open() {
    this.onopen?.();
  }

  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }

  disconnect() {
    this.onclose?.();
  }
}

afterEach(() => {
  vi.useRealTimers();
});

describe('teacher session event stream', () => {
  it('reconnects and ignores replayed event ids', async () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const urls: string[] = [];
    const stream = createTeacherSessionEvents(
      { baseUrl: 'https://core.example.test' },
      {
        reconnectDelayMs: 50,
        createSocket: (url) => {
          urls.push(url);
          const socket = new FakeSocket();
          sockets.push(socket);
          return socket;
        },
      },
    );
    const received: string[] = [];
    const states: string[] = [];
    const sessionId = 'a13e08ea-220f-458a-95f6-95b7c3a3f14c';
    const event = {
      eventId: '20000000-0000-4000-8000-000000000001',
      sessionId,
      type: 'service.status_changed',
      timestamp: '2026-09-25T12:00:00.000Z',
      source: 'core',
      payload: {},
    };

    const unsubscribe = stream.subscribe(
      sessionId,
      (item) => received.push(item.eventId),
      (state) => states.push(state),
    );
    expect(urls).toEqual([
      `wss://core.example.test/ws/sessions/${sessionId}/events`,
    ]);
    expect(states).toEqual(['connecting']);

    sockets[0].open();
    sockets[0].message(event);
    sockets[0].message(event);
    sockets[0].message({
      ...event,
      eventId: '20000000-0000-4000-8000-000000000099',
      sessionId: 'b13e08ea-220f-458a-95f6-95b7c3a3f14c',
    });
    expect(received).toEqual([event.eventId]);

    sockets[0].disconnect();
    expect(states.at(-1)).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(50);
    expect(sockets).toHaveLength(2);
    expect(urls[1]).toBe(
      `wss://core.example.test/ws/sessions/${sessionId}/events?afterEventId=${event.eventId}`,
    );

    sockets[1].open();
    sockets[1].message(event);
    sockets[1].message({
      ...event,
      eventId: '20000000-0000-4000-8000-000000000002',
    });
    expect(received).toEqual([
      '20000000-0000-4000-8000-000000000001',
      '20000000-0000-4000-8000-000000000002',
    ]);
    expect(states.at(-1)).toBe('connected');

    unsubscribe();
    expect(sockets[1].closed).toBe(true);
  });
});
