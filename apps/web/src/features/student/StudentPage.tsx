import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  Paper,
  Progress,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
} from '@mantine/core';
import {
  IconAlertCircle,
  IconBulb,
  IconCheck,
  IconClock,
  IconDeviceFloppy,
  IconSend,
  IconShieldCheck,
  IconX,
} from '@tabler/icons-react';
import { ErrorState, LoadingState } from '../../shared/StatePlaceholder';
import { incidentTypeOptions, serviceOptions } from './api/student.fixture';
import { studentMockApi } from './api/studentMockApi';
import type {
  StudentApi,
  StudentAssignment,
  StudentOperatorCard,
  StudentSessionReport,
} from './api/types';

type CardField = 'incidentType' | 'address' | 'description' | 'requiredServices';
type CardErrors = Partial<Record<CardField, string>>;
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

function formatTimer(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const seconds = (totalSeconds % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function useRemainingTime(startedAt: string | undefined, limitSeconds: number, stopped: boolean) {
  const [remaining, setRemaining] = useState(limitSeconds);

  useEffect(() => {
    if (!startedAt) return;
    const update = () => {
      const elapsed = Math.floor((Date.now() - Date.parse(startedAt)) / 1000);
      setRemaining(Math.max(0, limitSeconds - elapsed));
    };
    update();
    if (stopped) return;
    const intervalId = window.setInterval(update, 1000);
    return () => window.clearInterval(intervalId);
  }, [limitSeconds, startedAt, stopped]);

  return { formatted: formatTimer(remaining), isLow: remaining <= 60 };
}

function validateCard(card: StudentOperatorCard): CardErrors {
  const errors: CardErrors = {};
  if (!card.incidentType) errors.incidentType = 'Выберите тип происшествия.';
  if (!card.address?.trim()) errors.address = 'Укажите адрес происшествия.';
  if (!String(card.facts.description ?? '').trim()) errors.description = 'Опишите обстоятельства происшествия.';
  if (card.requiredServices.length === 0) errors.requiredServices = 'Выберите хотя бы одну необходимую службу.';
  return errors;
}

function ReportView({ report }: { report: StudentSessionReport }) {
  const passedCriteria = report.criteria.filter((criterion) => criterion.passed);

  return (
    <Stack className="student-report" gap="lg">
      <Paper className="report-hero" withBorder radius="lg" p="xl">
        <div className="report-score" aria-label={`Оценка ${report.score} из ${report.maxScore}`}>
          <Text className="report-score__value">{report.score}</Text>
          <Text size="sm" c="dimmed">из {report.maxScore}</Text>
        </div>
        <div className="report-hero__content">
          <Badge color={report.passed ? 'teal' : 'orange'} variant="light" size="lg">
            {report.passed ? 'Задание выполнено' : 'Нужна доработка'}
          </Badge>
          <Title order={2} mt="sm">Разбор карточки</Title>
          <Text c="dimmed" mt={6}>
            Mock-оценка показывает, что было сделано верно и где можно улучшить решение.
          </Text>
          <Progress
            value={(report.score / report.maxScore) * 100}
            color={report.passed ? 'teal' : 'orange'}
            size="md"
            radius="xl"
            mt="lg"
            aria-label="Доля набранных баллов"
          />
        </div>
      </Paper>

      <div className="report-grid">
        <Paper withBorder radius="lg" p="xl">
          <Group gap="sm" mb="lg">
            <ThemeIcon color="teal" variant="light" radius="xl">
              <IconShieldCheck size={19} />
            </ThemeIcon>
            <div>
              <Title order={3}>Выполненные критерии</Title>
              <Text size="sm" c="dimmed">{passedCriteria.length} из {report.criteria.length}</Text>
            </div>
          </Group>
          <Stack gap="sm">
            {passedCriteria.map((criterion) => (
              <div className="criterion-row" key={criterion.code}>
                <IconCheck size={19} className="criterion-row__success" aria-hidden="true" />
                <div>
                  <Text size="sm" fw={650}>{criterion.message}</Text>
                  <Text size="xs" c="dimmed" mt={2}>{criterion.points} / {criterion.maxPoints} баллов</Text>
                </div>
              </div>
            ))}
          </Stack>
        </Paper>

        <Paper withBorder radius="lg" p="xl">
          <Group gap="sm" mb="lg">
            <ThemeIcon color={report.errors.length ? 'red' : 'teal'} variant="light" radius="xl">
              {report.errors.length ? <IconX size={19} /> : <IconCheck size={19} />}
            </ThemeIcon>
            <div>
              <Title order={3}>Ошибки</Title>
              <Text size="sm" c="dimmed">
                {report.errors.length ? `${report.errors.length} замечания` : 'Критичных ошибок нет'}
              </Text>
            </div>
          </Group>
          {report.errors.length ? (
            <Stack gap="sm">
              {report.errors.map((error) => (
                <div className="criterion-row criterion-row--error" key={error.code}>
                  <IconX size={18} aria-hidden="true" />
                  <Text size="sm">{error.message}</Text>
                </div>
              ))}
            </Stack>
          ) : (
            <Text size="sm">Карточка совпадает с ожидаемым решением сценария.</Text>
          )}
        </Paper>
      </div>

      <Paper className="recommendations" withBorder radius="lg" p="md">
        <Group align="flex-start" gap="md" wrap="nowrap">
          <ThemeIcon className="recommendations__icon" color="blue" variant="light" radius="md" size={34}>
            <IconBulb size={18} aria-hidden="true" />
          </ThemeIcon>
          <div className="recommendations__content">
            <Title className="recommendations__title" order={3}>Рекомендации</Title>
            <Stack component="ul" gap={4} className="recommendations__list">
              {report.recommendations.map((recommendation) => (
                <Text component="li" size="sm" c="dimmed" key={recommendation}>
                  {recommendation}
                </Text>
              ))}
            </Stack>
          </div>
        </Group>
      </Paper>
    </Stack>
  );
}

export function StudentPage({ api = studentMockApi }: { api?: StudentApi }) {
  const [assignment, setAssignment] = useState<StudentAssignment | null>(null);
  const [card, setCard] = useState<StudentOperatorCard | null>(null);
  const [report, setReport] = useState<StudentSessionReport | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [errors, setErrors] = useState<CardErrors>({});
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const saveRevision = useRef(0);

  const loadAssignment = useCallback(async () => {
    setLoadError(false);
    setAssignment(null);
    try {
      const loaded = await api.getAssignment();
      setAssignment(loaded);
      setCard(loaded.session.card);
      setReport(loaded.session.report);
      const hasDraft = Boolean(
        loaded.session.card.incidentType
        || loaded.session.card.address
        || loaded.session.card.requiredServices.length
        || loaded.session.card.facts.description,
      );
      setSaveStatus(hasDraft ? 'saved' : 'idle');
    } catch {
      setLoadError(true);
    }
  }, [api]);

  useEffect(() => {
    void loadAssignment();
  }, [loadAssignment]);

  const timer = useRemainingTime(
    assignment?.session.startedAt,
    assignment?.scenario.timeLimitSeconds ?? 0,
    Boolean(report),
  );

  const saveStatusText = useMemo(() => ({
    idle: '',
    saving: 'Сохраняем черновик…',
    saved: 'Черновик сохранён локально',
    error: 'Не удалось сохранить черновик',
  }[saveStatus]), [saveStatus]);

  function updateCard(nextCard: StudentOperatorCard, field: CardField) {
    if (!assignment) return;
    setCard(nextCard);
    setErrors((current) => ({ ...current, [field]: undefined }));
    setSubmitError('');
    setSaveStatus('saving');
    const revision = ++saveRevision.current;
    void api.saveCard(assignment.session.id, nextCard)
      .then(() => {
        if (revision === saveRevision.current) setSaveStatus('saved');
      })
      .catch(() => {
        if (revision === saveRevision.current) setSaveStatus('error');
      });
  }

  async function submitCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment || !card) return;
    const nextErrors = validateCard(card);
    setErrors(nextErrors);
    setSubmitError('');
    if (Object.keys(nextErrors).length > 0) {
      setSubmitError('Заполните обязательные поля перед отправкой карточки.');
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await api.submitCard(assignment.session.id, card);
      setReport(result);
    } catch {
      setSubmitError('Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.');
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <ErrorState
        title="Не удалось получить задание"
        description="Повторите попытку — сохранённый черновик останется на этом устройстве."
        onRetry={() => void loadAssignment()}
      />
    );
  }

  if (!assignment || !card) {
    return <LoadingState title="Получаем задание" description="Подготавливаем сценарий и карточку происшествия." />;
  }

  return (
    <Stack className="student-page" gap="xl">
      <Group justify="space-between" align="flex-start" gap="md">
        <div>
          <Text className="page-eyebrow">Учебная сессия</Text>
          <Title order={1}>{report ? 'Результат задания' : 'Моё задание'}</Title>
          <Text c="dimmed" mt={5}>
            {report ? 'Изучите разбор mock-оценки.' : 'Изучите сообщение и заполните карточку происшествия.'}
          </Text>
        </div>
        {!report && saveStatus !== 'idle' && (
          <Group className={`save-indicator save-indicator--${saveStatus}`} gap={7} wrap="nowrap">
            <IconDeviceFloppy size={16} aria-hidden="true" />
            <Text size="xs">{saveStatusText}</Text>
          </Group>
        )}
      </Group>

      <Paper className="assignment-brief" withBorder radius="lg" p="xl">
        <div className="assignment-brief__main">
          <Title order={2}>{assignment.scenario.title}</Title>
          <Text className="assignment-brief__profile" mt="sm">{assignment.scenario.profile}</Text>
        </div>
        <div className={`assignment-timer${timer.isLow ? ' assignment-timer--low' : ''}`}>
          <IconClock size={21} stroke={1.8} aria-hidden="true" />
          <div>
            <Text size="xs">Осталось</Text>
            <Text className="assignment-timer__value" data-testid="assignment-timer">{timer.formatted}</Text>
          </div>
        </div>
      </Paper>

      {report ? (
        <ReportView report={report} />
      ) : (
        <Paper component="form" className="incident-form" withBorder radius="lg" p="xl" onSubmit={submitCard} noValidate>
          <div>
            <Title order={2}>Карточка происшествия</Title>
            <Text c="dimmed" size="sm" mt={5}>Поля со звёздочкой обязательны.</Text>
          </div>

          {submitError && (
            <Alert
              color="red"
              icon={<IconAlertCircle size={18} />}
              withCloseButton
              onClose={() => setSubmitError('')}
            >
              {submitError}
            </Alert>
          )}

          <div className="incident-form__grid">
            <Select
              label="Тип происшествия"
              placeholder="Выберите тип"
              data={incidentTypeOptions}
              value={card.incidentType}
              onChange={(value) => updateCard({ ...card, incidentType: value }, 'incidentType')}
              error={errors.incidentType}
              required
              searchable
            />
            <TextInput
              label="Адрес"
              placeholder="Улица, дом, корпус"
              value={card.address ?? ''}
              onChange={(event) => updateCard({ ...card, address: event.currentTarget.value }, 'address')}
              error={errors.address}
              required
            />
          </div>

          <Textarea
            label="Описание"
            description="Кратко зафиксируйте обстоятельства, угрозы и сведения о людях."
            placeholder="Что произошло и кому может требоваться помощь"
            minRows={5}
            value={String(card.facts.description ?? '')}
            onChange={(event) => updateCard({
              ...card,
              facts: { ...card.facts, description: event.currentTarget.value },
            }, 'description')}
            error={errors.description}
            required
          />

          <div>
            <Text component="label" fw={500} size="sm">
              Необходимые службы <Text component="span" c="red" aria-hidden="true">*</Text>
            </Text>
            <Text size="xs" c="dimmed" mt={3}>Можно выбрать несколько вариантов.</Text>
            <Checkbox.Group
              value={card.requiredServices}
              onChange={(value) => updateCard({ ...card, requiredServices: value }, 'requiredServices')}
            >
              <div className="service-options">
                {serviceOptions.map((service) => (
                  <Checkbox.Card key={service.value} value={service.value} radius="md" p="md">
                    <Group wrap="nowrap" align="flex-start">
                      <Checkbox.Indicator />
                      <Text size="sm" fw={550}>{service.label}</Text>
                    </Group>
                  </Checkbox.Card>
                ))}
              </div>
            </Checkbox.Group>
            {errors.requiredServices && (
              <Text c="red" size="xs" mt={6} role="alert">{errors.requiredServices}</Text>
            )}
          </div>

          <Divider />
          <Group justify="space-between" gap="md" className="incident-form__footer">
            <Text size="xs" c="dimmed">После отправки изменить карточку будет нельзя.</Text>
            <Button type="submit" leftSection={<IconSend size={17} />} loading={isSubmitting}>
              Отправить на оценку
            </Button>
          </Group>
        </Paper>
      )}
    </Stack>
  );
}
