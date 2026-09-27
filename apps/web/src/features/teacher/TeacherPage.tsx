import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  Select,
  SegmentedControl,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { IconAlertCircle, IconClock, IconPlayerPlay, IconPlayerStop } from '@tabler/icons-react';
import { getApiErrorMessage } from '../../api/errors';
import { secureAuth } from '../../api/auth';
import { getScenarioCategoryLabel } from '../../api/scenarioLabels';
import type { ServiceStatus } from '../../api/types';
import { EmptyState, ErrorState, LoadingState } from '../../shared/StatePlaceholder';
import { teacherApi, teacherSessionEvents } from './api/teacherApi';
import { TeacherAnalytics } from './TeacherAnalytics';
import type {
  ScenarioDifficulty,
  TeacherApi,
  TeacherAnalyticsSummary,
  TeacherLiveConnectionState,
  TeacherScenario,
  TeacherServiceAssignment,
  TeacherSession,
  TeacherSessionEvents,
} from './api/types';

type DifficultyFilter = 'ALL' | ScenarioDifficulty;

const difficultyLabels: Record<ScenarioDifficulty, string> = {
  BASIC: 'Базовая',
  INTERMEDIATE: 'Средняя',
  ADVANCED: 'Высокая',
};

const statusLabels: Record<TeacherScenario['status'], string> = {
  READY: 'Готов',
  DRAFT: 'Черновик',
};

const serviceStatusLabels: Record<ServiceStatus, string> = {
  ADDED: 'Назначена',
  RECEIVED: 'Получена',
  ACCEPTED: 'Принята',
  RESPONDING: 'Следует к месту',
  ARRIVED: 'Прибыла',
  COMPLETED: 'Завершена',
  REFUSED: 'Отказ',
  FAILED: 'Ошибка',
};

const serviceStatusColors: Record<ServiceStatus, string> = {
  ADDED: 'gray',
  RECEIVED: 'blue',
  ACCEPTED: 'cyan',
  RESPONDING: 'indigo',
  ARRIVED: 'violet',
  COMPLETED: 'teal',
  REFUSED: 'orange',
  FAILED: 'red',
};

const liveStateLabels: Record<TeacherLiveConnectionState, string> = {
  connecting: 'Подключение',
  connected: 'Онлайн',
  reconnecting: 'Переподключение',
  polling: 'Опрос Core',
};

function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(date);
}

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const seconds = (totalSeconds % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function useSessionTimer(session: TeacherSession | null) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!session?.startedAt) {
      setElapsedSeconds(0);
      return;
    }

    const startedAt = Date.parse(session.startedAt);
    const update = () => {
      const end = session.endedAt ? Date.parse(session.endedAt) : Date.now();
      setElapsedSeconds(Math.max(0, Math.floor((end - startedAt) / 1000)));
    };

    update();
    if (session.state !== 'ACTIVE') return;

    const intervalId = window.setInterval(update, 1000);
    return () => window.clearInterval(intervalId);
  }, [session]);

  return formatDuration(elapsedSeconds);
}

type TeacherPageProps = {
  api?: TeacherApi;
  sessionEvents?: TeacherSessionEvents;
  pollIntervalMs?: number;
};

export function TeacherPage({
  api = teacherApi,
  sessionEvents = teacherSessionEvents,
  pollIntervalMs = 3000,
}: TeacherPageProps) {
  const [scenarios, setScenarios] = useState<TeacherScenario[] | null>(null);
  const [difficulty, setDifficulty] = useState<DifficultyFilter>('ALL');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [students, setStudents] = useState<{ id: string; displayName: string; username: string }[]>([]);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [session, setSession] = useState<TeacherSession | null>(null);
  const [serviceAssignments, setServiceAssignments] = useState<TeacherServiceAssignment[] | null>(null);
  const [assignmentsError, setAssignmentsError] = useState('');
  const [liveState, setLiveState] = useState<TeacherLiveConnectionState>('connecting');
  const [listError, setListError] = useState('');
  const [operationError, setOperationError] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [analytics, setAnalytics] = useState<TeacherAnalyticsSummary | null>(null);
  const [analyticsError, setAnalyticsError] = useState('');
  const timer = useSessionTimer(session);

  const loadAnalytics = useCallback(async () => {
    setAnalyticsError('');
    setAnalytics(null);
    try {
      setAnalytics(await api.getAnalytics());
    } catch (error) {
      setAnalyticsError(getApiErrorMessage(error, 'Не удалось загрузить сводку.'));
    }
  }, [api]);

  const loadScenarios = useCallback(async () => {
    setListError('');
    setScenarios(null);
    try {
      const [items, savedSession] = await Promise.all([
        api.getScenarios(),
        api.getCurrentSession(),
      ]);
      setScenarios(items);
      setSession(savedSession);
      setSelectedId((current) => {
        if (savedSession && items.some((item) => item.id === savedSession.scenarioId)) {
          return savedSession.scenarioId;
        }
        return current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null;
      });
    } catch (error) {
      setListError(getApiErrorMessage(error, 'Не удалось загрузить сценарии.'));
    }
  }, [api]);

  useEffect(() => {
    void loadScenarios();
  }, [loadScenarios]);

  useEffect(() => {
    void loadAnalytics();
  }, [loadAnalytics]);

  useEffect(() => {
    if (session?.state === 'SCORED' && session.report) void loadAnalytics();
  }, [loadAnalytics, session?.id, session?.report?.score, session?.state]);

  useEffect(() => {
    if (secureAuth && api.getStudents) {
      void api.getStudents().then((items) => {
        setStudents(items);
        setStudentId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null);
      }).catch(() => setOperationError('Не удалось загрузить список студентов группы.'));
    }
  }, [api]);

  useEffect(() => {
    const sessionId = session?.id;
    if (!sessionId) {
      setServiceAssignments(null);
      setAssignmentsError('');
      return;
    }

    let disposed = false;
    let refreshInFlight = false;
    let refreshPending = false;

    const refreshSnapshot = async (showAssignmentError = false) => {
      if (refreshInFlight) {
        refreshPending = true;
        return;
      }
      refreshInFlight = true;
      do {
        refreshPending = false;
        const results: [
          PromiseSettledResult<TeacherSession | null>,
          PromiseSettledResult<TeacherServiceAssignment[]>,
        ] = await Promise.allSettled([
          api.getCurrentSession(),
          api.getServiceAssignments(sessionId),
        ]);
        const sessionResult = results[0];
        const assignmentsResult = results[1];
        if (disposed) return;

        if (sessionResult.status === 'fulfilled') {
          if (sessionResult.value === null) setSession(null);
          else if (sessionResult.value.id === sessionId) setSession(sessionResult.value);
        }

        if (assignmentsResult.status === 'fulfilled') {
          setServiceAssignments(assignmentsResult.value.filter((item) => item.sessionId === sessionId));
          setAssignmentsError('');
        } else if (showAssignmentError) {
          setAssignmentsError(getApiErrorMessage(
            assignmentsResult.reason,
            'Не удалось загрузить назначения служб. Повторим автоматически.',
          ));
        }
      } while (refreshPending && !disposed);
      refreshInFlight = false;
    };

    setServiceAssignments(null);
    setAssignmentsError('');
    void refreshSnapshot(true);

    const unsubscribe = sessionEvents.subscribe(
      sessionId,
      () => { void refreshSnapshot(); },
      setLiveState,
    );
    const intervalId = window.setInterval(() => { void refreshSnapshot(); }, pollIntervalMs);

    return () => {
      disposed = true;
      unsubscribe();
      window.clearInterval(intervalId);
    };
  }, [api, pollIntervalMs, session?.id, sessionEvents]);

  const visibleScenarios = useMemo(() => (
    scenarios?.filter((scenario) => difficulty === 'ALL' || scenario.difficulty === difficulty) ?? []
  ), [difficulty, scenarios]);

  useEffect(() => {
    if (visibleScenarios.length > 0 && !visibleScenarios.some((item) => item.id === selectedId)) {
      setSelectedId(visibleScenarios[0].id);
    }
  }, [selectedId, visibleScenarios]);

  const selectedScenario = scenarios?.find((scenario) => scenario.id === selectedId) ?? null;
  const sessionScenario = session
    ? scenarios?.find((scenario) => scenario.id === session.scenarioId) ?? null
    : null;

  async function launchSession() {
    if (!selectedScenario) return;
    setOperationError('');
    setIsLaunching(true);
    try {
      if (secureAuth && !studentId) throw new Error('Выберите студента');
      setSession(await api.launchSession(selectedScenario.id, studentId ?? undefined));
    } catch (error) {
      setOperationError(getApiErrorMessage(error, 'Не удалось запустить занятие. Попробуйте ещё раз.'));
    } finally {
      setIsLaunching(false);
    }
  }

  async function stopSession() {
    if (!session) return;
    setOperationError('');
    setIsStopping(true);
    try {
      setSession(await api.stopSession(session.id));
    } catch (error) {
      setOperationError(getApiErrorMessage(error, 'Не удалось завершить занятие. Попробуйте ещё раз.'));
    } finally {
      setIsStopping(false);
    }
  }

  async function clearSession() {
    setOperationError('');
    setIsClearing(true);
    try {
      await api.clearSession();
      setSession(null);
    } catch (error) {
      setOperationError(getApiErrorMessage(error, 'Не удалось очистить сессию. Попробуйте ещё раз.'));
    } finally {
      setIsClearing(false);
    }
  }

  return (
    <Stack className="teacher-page" gap="xl">
      <div>
        <Title order={1}>Сценарии</Title>
        <Text c="dimmed" mt={5}>Выберите сценарий и запустите учебную сессию.</Text>
      </div>

      <TeacherAnalytics
        summary={analytics}
        error={analyticsError}
        onRetry={() => void loadAnalytics()}
      />

      {operationError && (
        <Alert color="red" icon={<IconAlertCircle size={18} />} withCloseButton onClose={() => setOperationError('')}>
          {operationError}
        </Alert>
      )}

      {listError ? (
        <ErrorState
          title="Не удалось загрузить сценарии"
          description={listError}
          onRetry={() => void loadScenarios()}
        />
      ) : scenarios === null ? (
        <LoadingState title="Загружаем сценарии" />
      ) : scenarios.length === 0 ? (
        <EmptyState title="Сценариев нет" description="Добавленные сценарии появятся здесь." />
      ) : (
        <>
          <SegmentedControl
            className="difficulty-filter"
            aria-label="Фильтр по сложности"
            value={difficulty}
            onChange={(value) => setDifficulty(value as DifficultyFilter)}
            data={[
              { value: 'ALL', label: 'Все' },
              { value: 'BASIC', label: 'Базовая' },
              { value: 'INTERMEDIATE', label: 'Средняя' },
              { value: 'ADVANCED', label: 'Высокая' },
            ]}
          />

          {visibleScenarios.length === 0 ? (
            <EmptyState title="Ничего не найдено" description="Выберите другую сложность." />
          ) : (
            <div className="teacher-layout">
              <Stack gap="sm" className="scenario-list" aria-label="Список сценариев">
                {visibleScenarios.map((scenario) => (
                  <UnstyledButton
                    key={scenario.id}
                    className="scenario-card"
                    data-selected={scenario.id === selectedId || undefined}
                    onClick={() => setSelectedId(scenario.id)}
                    disabled={session?.state === 'ACTIVE'}
                    aria-label={`Открыть сценарий «${scenario.title}»`}
                  >
                    <Group justify="space-between" gap="sm" wrap="nowrap">
                      <div>
                        <Text fw={650}>{scenario.title}</Text>
                        <Text size="sm" c="dimmed" mt={3}>{getScenarioCategoryLabel(scenario.category)}</Text>
                      </div>
                      <Stack gap={5} align="flex-end">
                        <Badge color={scenario.status === 'READY' ? 'teal' : 'gray'} variant="light">
                          {statusLabels[scenario.status]}
                        </Badge>
                        <Text size="xs" c="dimmed">{difficultyLabels[scenario.difficulty]}</Text>
                      </Stack>
                    </Group>
                  </UnstyledButton>
                ))}
              </Stack>

              <div className={`teacher-panel-slot${session ? ' teacher-panel-slot--session' : ''}`}>
                {session ? (
                  <Paper className="session-panel" withBorder radius="lg" p="xl">
                  <Group justify="space-between" mb="xl" align="flex-start">
                    <Text fw={650}>Учебная сессия</Text>
                    <Group gap="xs" justify="flex-end">
                      <Badge
                        color={liveState === 'connected' ? 'teal' : liveState === 'reconnecting' ? 'orange' : 'gray'}
                        variant="dot"
                      >
                        {liveStateLabels[liveState]}
                      </Badge>
                      <Badge
                        color={session.state === 'ACTIVE' ? 'teal' : session.state === 'FAILED' ? 'red' : 'gray'}
                        variant="light"
                        size="lg"
                      >
                        {session.state}
                      </Badge>
                    </Group>
                  </Group>
                  {liveState === 'reconnecting' && (
                    <Alert color="orange" mb="lg" title="Живые события временно недоступны">
                      Последнее состояние сохранено. Интерфейс продолжает обновляться через Core каждые 3 секунды.
                    </Alert>
                  )}
                  {sessionScenario && (
                    <section className="session-scenario" aria-label="Информация о сценарии">
                      <Title order={2}>{sessionScenario.title}</Title>
                      <Text c="dimmed" mt="xs" className="session-scenario__description">
                        {sessionScenario.profile}
                      </Text>
                      <div className="session-meta">
                        <div>
                          <Text size="xs" c="dimmed">Категория</Text>
                          <Text size="sm" fw={600} mt={3}>{getScenarioCategoryLabel(sessionScenario.category)}</Text>
                        </div>
                        <div>
                          <Text size="xs" c="dimmed">Сложность</Text>
                          <Text size="sm" fw={600} mt={3}>
                            {difficultyLabels[sessionScenario.difficulty]}
                          </Text>
                        </div>
                        <div>
                          <Text size="xs" c="dimmed">Лимит времени</Text>
                          <Text size="sm" fw={600} mt={3}>
                            {sessionScenario.timeLimitSeconds
                              ? `${Math.round(sessionScenario.timeLimitSeconds / 60)} мин`
                              : 'Не задан'}
                          </Text>
                        </div>
                      </div>
                    </section>
                  )}
                  <Stack align="center" gap="xs" className="session-timer">
                    <IconClock size={25} stroke={1.7} aria-hidden="true" />
                    <Text className="session-timer__value" data-testid="session-timer">{timer}</Text>
                    <Text size="sm" c="dimmed">Время занятия</Text>
                  </Stack>
                  <Divider my="xl" />
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Идентификатор сессии</Text>
                  <Text className="session-id" mt={5}>{session.id}</Text>
                  <section className="teacher-services" aria-labelledby="teacher-services-title">
                    <Group justify="space-between" align="baseline" mb="sm">
                      <Title order={3} id="teacher-services-title">Службы ДДС</Title>
                      {serviceAssignments && serviceAssignments.length > 0 && (
                        <Text size="xs" c="dimmed">Назначено: {serviceAssignments.length}</Text>
                      )}
                    </Group>
                    {assignmentsError && serviceAssignments === null ? (
                      <Alert color="orange" title="Назначения пока недоступны">{assignmentsError}</Alert>
                    ) : serviceAssignments === null ? (
                      <Text size="sm" c="dimmed">Загружаем назначения…</Text>
                    ) : serviceAssignments.length === 0 ? (
                      <div className="teacher-services__empty">
                        <Text fw={600}>Службы ещё не назначены</Text>
                        <Text size="sm" c="dimmed" mt={3}>
                          Назначения появятся после отправки карточки. Это нормальное состояние занятия.
                        </Text>
                      </div>
                    ) : (
                      <Stack gap="sm">
                        {serviceAssignments.map((assignment) => (
                          <article className="teacher-service" key={assignment.id}>
                            <Group justify="space-between" align="flex-start" wrap="nowrap">
                              <div>
                                <Text fw={650}>{assignment.displayName}</Text>
                                <Text size="xs" c="dimmed" mt={3}>
                                  Изменено: {formatTimestamp(assignment.updatedAt)}
                                </Text>
                              </div>
                              <Group gap={6} justify="flex-end">
                                {assignment.overdue && <Badge color="red" variant="light">Просрочено</Badge>}
                                <Badge color={serviceStatusColors[assignment.status]} variant="light">
                                  {serviceStatusLabels[assignment.status]}
                                </Badge>
                              </Group>
                            </Group>
                            <details className="teacher-service__history">
                              <summary>История статусов ({assignment.history.length})</summary>
                              <ol>
                                {assignment.history.map((entry) => (
                                  <li key={entry.eventId}>
                                    <Text size="sm" component="span" fw={600}>
                                      {serviceStatusLabels[entry.status]}
                                    </Text>{' '}
                                    <Text size="xs" component="span" c="dimmed">
                                      {formatTimestamp(entry.timestamp)}
                                    </Text>
                                    {(entry.comment || entry.refusalReason) && (
                                      <Text size="xs" c="dimmed">
                                        {entry.refusalReason ?? entry.comment}
                                      </Text>
                                    )}
                                  </li>
                                ))}
                              </ol>
                            </details>
                          </article>
                        ))}
                      </Stack>
                    )}
                  </section>
                  {session.report && (
                    <Alert color={session.report.passed ? 'teal' : 'orange'} mt="xl" title="Результат занятия">
                      Оценка: {session.report.score} из {session.report.maxScore}.{' '}
                      {session.report.passed ? 'Задание выполнено.' : 'Нужна доработка.'}
                    </Alert>
                  )}
                  {session.state === 'ACTIVE' ? (
                    <Button
                      color="red"
                      variant="light"
                      fullWidth
                      mt="xl"
                      leftSection={<IconPlayerStop size={18} />}
                      loading={isStopping}
                      onClick={() => void stopSession()}
                    >
                      Завершить занятие
                    </Button>
                  ) : (
                    <Button
                      fullWidth
                      mt="xl"
                      variant="light"
                      loading={isClearing}
                      onClick={() => void clearSession()}
                    >
                      Новое занятие
                    </Button>
                  )}
                  </Paper>
                ) : selectedScenario ? (
                  <Paper className="scenario-details" withBorder radius="lg" p="xl">
                  <Group gap="xs" mb="md">
                    <Badge variant="light">{difficultyLabels[selectedScenario.difficulty]}</Badge>
                    <Badge color={selectedScenario.status === 'READY' ? 'teal' : 'gray'} variant="light">
                      {statusLabels[selectedScenario.status]}
                    </Badge>
                  </Group>
                  <Title order={2}>{selectedScenario.title}</Title>
                  <Text c="dimmed" mt="md" className="scenario-details__description">
                    {selectedScenario.profile}
                  </Text>
                  <Divider my="xl" />
                  <Group justify="space-between">
                    <div>
                      <Text size="xs" c="dimmed">Категория</Text>
                      <Text size="sm" fw={600} mt={3}>{getScenarioCategoryLabel(selectedScenario.category)}</Text>
                    </div>
                    <div>
                      <Text size="xs" c="dimmed">Лимит времени</Text>
                      <Text size="sm" fw={600} mt={3}>
                        {selectedScenario.timeLimitSeconds
                          ? `${Math.round(selectedScenario.timeLimitSeconds / 60)} мин`
                          : 'Не задан'}
                      </Text>
                    </div>
                  </Group>
                  {secureAuth && <Select mt="xl" label="Студент группы" placeholder="Выберите студента"
                    data={students.map((item) => ({ value: item.id, label: `${item.displayName} (${item.username})` }))}
                    value={studentId} onChange={setStudentId} />}
                  <Button
                    fullWidth
                    mt="xl"
                    leftSection={<IconPlayerPlay size={18} />}
                    disabled={selectedScenario.status !== 'READY' || (secureAuth && !studentId)}
                    loading={isLaunching}
                    onClick={() => void launchSession()}
                  >
                    {selectedScenario.status === 'READY' ? 'Запустить занятие' : 'Сценарий не готов'}
                  </Button>
                  </Paper>
                ) : null}
              </div>
            </div>
          )}
        </>
      )}
    </Stack>
  );
}
