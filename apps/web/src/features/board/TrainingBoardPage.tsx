import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, Loader, Paper, Text, Title } from '@mantine/core';
import {
  IconAlertTriangle,
  IconChartBar,
  IconClock,
  IconPhoneCall,
  IconRefresh,
  IconSchool,
} from '@tabler/icons-react';
import { getApiErrorMessage } from '../../api/errors';
import { Brand } from '../../shared/Brand';
import { trainingBoardApi } from './api/trainingBoardApi';
import type { TrainingBoardApi, TrainingBoardSession, TrainingBoardState } from './api/types';

type BoardConnectionState = 'loading' | 'online' | 'offline';

const stageLabels: Record<TrainingBoardState, string> = {
  CREATED: 'Создано',
  READY: 'Готово к старту',
  RINGING: 'Вызов',
  ACTIVE: 'Идёт занятие',
  SCORING: 'Оценивание',
};

const stageColors: Record<TrainingBoardState, string> = {
  CREATED: 'gray',
  READY: 'blue',
  RINGING: 'orange',
  ACTIVE: 'teal',
  SCORING: 'indigo',
};

function formatPercent(value: number | null) {
  return value === null
    ? '—'
    : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)}%`;
}

function formatTimestamp(value: string | null) {
  if (value === null) return 'ожидает ответа';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

function SessionCard({ session }: { session: TrainingBoardSession }) {
  const ModeIcon = session.mode === 'VOICE' ? IconPhoneCall : IconSchool;
  return (
    <Paper component="article" className="training-board__session" withBorder>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <span className="training-board__mode-icon" aria-hidden="true"><ModeIcon size={28} /></span>
        <Badge color={stageColors[session.state]} size="xl" variant="light">
          {stageLabels[session.state]}
        </Badge>
      </Group>
      <Text className="training-board__mode" mt="lg">
        {session.mode === 'VOICE' ? 'Учебный звонок' : 'Карточное занятие'}
      </Text>
      <Title order={3} mt={4}>{session.scenarioTitle}</Title>
      <Group className="training-board__session-time" gap="xs" mt="xl">
        <IconClock size={19} aria-hidden="true" />
        <Text>Старт: {formatTimestamp(session.startedAt)}</Text>
      </Group>
      <Text size="sm" c="dimmed" mt={5}>Данные Core: {formatTimestamp(session.updatedAt)}</Text>
    </Paper>
  );
}

type TrainingBoardPageProps = {
  api?: TrainingBoardApi;
  pollIntervalMs?: number;
};

export function TrainingBoardPage({
  api = trainingBoardApi,
  pollIntervalMs = 3000,
}: TrainingBoardPageProps) {
  const [snapshot, setSnapshot] = useState<Awaited<ReturnType<TrainingBoardApi['getSnapshot']>> | null>(null);
  const [connection, setConnection] = useState<BoardConnectionState>('loading');
  const [error, setError] = useState('');
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    let disposed = false;
    let refreshInFlight = false;

    const refresh = async () => {
      if (refreshInFlight) return;
      refreshInFlight = true;
      try {
        const next = await api.getSnapshot();
        if (disposed) return;
        setSnapshot(next);
        setConnection('online');
        setError('');
      } catch (caught) {
        if (disposed) return;
        setConnection('offline');
        setError(getApiErrorMessage(caught, 'Не удалось получить снимок табло.'));
      } finally {
        refreshInFlight = false;
      }
    };

    void refresh();
    const intervalId = window.setInterval(() => void refresh(), pollIntervalMs);
    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, [api, pollIntervalMs, retryVersion]);

  const maxDistribution = Math.max(1, ...(snapshot?.analytics.scoreDistribution.map((item) => item.count) ?? []));

  return (
    <main className="training-board">
      <header className="training-board__header">
        <Brand />
        <div className="training-board__title">
          <Text className="training-board__eyebrow">Учебный контур · только агрегаты</Text>
          <Title order={1}>Оперативное табло</Title>
        </div>
        <div className="training-board__connection" role="status" aria-live="polite">
          <span className={`training-board__connection-dot training-board__connection-dot--${connection}`} />
          <div>
            <Text fw={750}>{connection === 'online' ? 'Связь с Core' : connection === 'offline' ? 'Связь потеряна' : 'Подключение'}</Text>
            <Text size="sm" c="dimmed">
              {snapshot ? `Обновлено ${formatTimestamp(snapshot.generatedAt)}` : 'Ожидаем первый снимок'}
            </Text>
          </div>
        </div>
      </header>

      {connection === 'offline' && (
        <Alert
          className="training-board__offline"
          color="orange"
          icon={<IconAlertTriangle size={24} />}
          title="Связь с Core потеряна"
        >
          <Group justify="space-between" align="center">
            <Text>{snapshot ? 'На экране сохранён последний успешный снимок. Повторяем подключение автоматически.' : error}</Text>
            <Button variant="light" color="orange" leftSection={<IconRefresh size={18} />} onClick={() => setRetryVersion((value) => value + 1)}>
              Повторить сейчас
            </Button>
          </Group>
        </Alert>
      )}

      {snapshot === null ? (
        <section className="training-board__loading" aria-label="Загрузка табло">
          {connection === 'loading' ? <Loader size="xl" /> : <IconAlertTriangle size={48} />}
          <Title order={2}>{connection === 'loading' ? 'Получаем данные Core' : 'Табло временно недоступно'}</Title>
          <Text c="dimmed">Экран продолжит попытки подключения без ручной перезагрузки.</Text>
        </section>
      ) : (
        <div className="training-board__content">
          <section className="training-board__kpis" aria-label="Сводные показатели">
            <Paper withBorder><Text>Сейчас в работе</Text><strong>{snapshot.activeSessions.length}</strong><small>занятий и звонков</small></Paper>
            <Paper withBorder><Text>Завершено</Text><strong>{snapshot.analytics.completedSessions}</strong><small>оценённых занятий</small></Paper>
            <Paper withBorder><Text>Средний результат</Text><strong>{formatPercent(snapshot.analytics.averagePercent)}</strong><small>медиана {formatPercent(snapshot.analytics.medianPercent)}</small></Paper>
          </section>

          <section className="training-board__main-grid">
            <div className="training-board__activity">
              <Group justify="space-between" align="baseline" mb="md">
                <Title order={2}>Активные занятия и звонки</Title>
                <Badge size="lg" variant="dot" color="teal">В эфире: {snapshot.activeSessions.length}</Badge>
              </Group>
              {snapshot.activeSessions.length === 0 ? (
                <Paper className="training-board__empty" withBorder role="status">
                  <IconClock size={36} aria-hidden="true" />
                  <Title order={3}>Нет активных занятий</Title>
                  <Text c="dimmed">Новые процессы появятся здесь автоматически.</Text>
                </Paper>
              ) : (
                <div className="training-board__session-grid" role="list" aria-label="Активные занятия и звонки">
                  {snapshot.activeSessions.map((session, index) => (
                    <div role="listitem" key={`${session.mode}-${session.startedAt}-${session.scenarioTitle}-${index}`}>
                      <SessionCard session={session} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <aside className="training-board__analytics" aria-label="Агрегированные результаты">
              <Paper className="training-board__panel" withBorder>
                <Group gap="sm" mb="lg"><IconChartBar size={25} aria-hidden="true" /><Title order={2}>Результаты</Title></Group>
                <div className="training-board__distribution" role="list" aria-label="Распределение результатов">
                  {snapshot.analytics.scoreDistribution.map((item) => (
                    <div role="listitem" key={item.label}>
                      <Group justify="space-between" gap="xs"><Text>{item.label}%</Text><Text fw={750}>{item.count}</Text></Group>
                      <div><span style={{ width: `${item.count / maxDistribution * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              </Paper>

              <Paper className="training-board__panel" withBorder>
                <Title order={2} mb="lg">Частые ошибки</Title>
                {snapshot.analytics.topErrors.length === 0 ? (
                  <Text c="dimmed">Ошибок по критериям не зафиксировано.</Text>
                ) : (
                  <div className="training-board__errors" role="list">
                    {snapshot.analytics.topErrors.slice(0, 5).map((item) => (
                      <div role="listitem" key={item.criterionCode}>
                        <Text ff="monospace" fw={700}>{item.criterionCode}</Text>
                        <Badge color="red" variant="light" size="lg">{item.count}</Badge>
                      </div>
                    ))}
                  </div>
                )}
              </Paper>
            </aside>
          </section>
        </div>
      )}
    </main>
  );
}
