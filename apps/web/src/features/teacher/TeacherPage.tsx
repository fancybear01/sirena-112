import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from '@mantine/core';
import { IconAlertCircle, IconClock, IconPlayerPlay, IconPlayerStop } from '@tabler/icons-react';
import { EmptyState, ErrorState, LoadingState } from '../../shared/StatePlaceholder';
import { teacherMockApi } from './api/teacherMockApi';
import type {
  ScenarioDifficulty,
  TeacherApi,
  TeacherScenario,
  TeacherSession,
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

export function TeacherPage({ api = teacherMockApi }: { api?: TeacherApi }) {
  const [scenarios, setScenarios] = useState<TeacherScenario[] | null>(null);
  const [difficulty, setDifficulty] = useState<DifficultyFilter>('ALL');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<TeacherSession | null>(null);
  const [listError, setListError] = useState(false);
  const [operationError, setOperationError] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const timer = useSessionTimer(session);

  const loadScenarios = useCallback(async () => {
    setListError(false);
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
    } catch {
      setListError(true);
    }
  }, [api]);

  useEffect(() => {
    void loadScenarios();
  }, [loadScenarios]);

  const visibleScenarios = useMemo(() => (
    scenarios?.filter((scenario) => difficulty === 'ALL' || scenario.difficulty === difficulty) ?? []
  ), [difficulty, scenarios]);

  useEffect(() => {
    if (visibleScenarios.length > 0 && !visibleScenarios.some((item) => item.id === selectedId)) {
      setSelectedId(visibleScenarios[0].id);
    }
  }, [selectedId, visibleScenarios]);

  const selectedScenario = scenarios?.find((scenario) => scenario.id === selectedId) ?? null;

  async function launchSession() {
    if (!selectedScenario) return;
    setOperationError('');
    setIsLaunching(true);
    try {
      setSession(await api.launchSession(selectedScenario.id));
    } catch {
      setOperationError('Не удалось запустить занятие. Попробуйте ещё раз.');
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
    } catch {
      setOperationError('Не удалось завершить занятие. Попробуйте ещё раз.');
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
    } catch {
      setOperationError('Не удалось очистить сессию. Попробуйте ещё раз.');
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

      {operationError && (
        <Alert color="red" icon={<IconAlertCircle size={18} />} withCloseButton onClose={() => setOperationError('')}>
          {operationError}
        </Alert>
      )}

      {listError ? (
        <ErrorState
          title="Не удалось загрузить сценарии"
          description="Проверьте соединение и повторите попытку."
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
                        <Text size="sm" c="dimmed" mt={3}>{scenario.category}</Text>
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

              {session ? (
                <Paper className="session-panel" withBorder radius="lg" p="xl">
                  <Group justify="space-between" mb="xl">
                    <Text fw={650}>Учебная сессия</Text>
                    <Badge color={session.state === 'ACTIVE' ? 'teal' : 'gray'} variant="light" size="lg">
                      {session.state}
                    </Badge>
                  </Group>
                  <Stack align="center" gap="xs" className="session-timer">
                    <IconClock size={25} stroke={1.7} aria-hidden="true" />
                    <Text className="session-timer__value" data-testid="session-timer">{timer}</Text>
                    <Text size="sm" c="dimmed">Время занятия</Text>
                  </Stack>
                  <Divider my="xl" />
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Идентификатор сессии</Text>
                  <Text className="session-id" mt={5}>{session.id}</Text>
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
                      <Text size="sm" fw={600} mt={3}>{selectedScenario.category}</Text>
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
                  <Button
                    fullWidth
                    mt="xl"
                    leftSection={<IconPlayerPlay size={18} />}
                    disabled={selectedScenario.status !== 'READY'}
                    loading={isLaunching}
                    onClick={() => void launchSession()}
                  >
                    {selectedScenario.status === 'READY' ? 'Запустить занятие' : 'Сценарий не готов'}
                  </Button>
                </Paper>
              ) : null}
            </div>
          )}
        </>
      )}
    </Stack>
  );
}
