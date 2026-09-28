import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  NumberInput,
  Paper,
  Progress,
  Radio,
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
  IconRoute,
  IconSend,
  IconShieldCheck,
  IconX,
} from '@tabler/icons-react';
import type {
  CardCalculation,
  CallerInput,
  QuestionAnswer,
  ServiceAssignment,
  ServiceStatus,
} from '../../api/types';
import { getApiErrorMessage } from '../../api/errors';
import { secureAuth } from '../../api/auth';
import { apiConfig } from '../../api/config';
import { createHttpClient } from '../../api/httpClient';
import { ErrorState, LoadingState } from '../../shared/StatePlaceholder';
import { studentApi } from './api/studentApi';
import { TrainingHistoryPanel } from '../history/TrainingHistoryPanel';
import type {
  StudentApi,
  StudentAssignment,
  StudentCardForm,
  StudentCardInput,
  StudentSession,
  StudentSessionReport,
} from './api/types';

type CardErrors = Record<string, string | undefined>;
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const emptyCaller: CallerInput = {
  phoneNumbers: [],
  fullName: null,
  status: null,
  communicationChannel: 'VOICE',
  language: 'ru',
};

function formatTimer(totalSeconds: number) {
  const safeSeconds = Math.max(0, totalSeconds);
  const minutes = Math.floor(safeSeconds / 60).toString().padStart(2, '0');
  const seconds = (safeSeconds % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function useSessionTimer(
  startedAt: string | undefined,
  endedAt: string | null | undefined,
  limitSeconds: number,
  stopped: boolean,
) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setNow(Date.now());
    if (stopped || endedAt) return;
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [endedAt, stopped]);

  const startedMs = startedAt ? Date.parse(startedAt) : now;
  const endedMs = endedAt ? Date.parse(endedAt) : now;
  const elapsedSeconds = Math.max(0, Math.floor((endedMs - startedMs) / 1000));
  const remainingSeconds = limitSeconds - elapsedSeconds;
  const isExceeded = remainingSeconds < 0;
  return {
    elapsedSeconds,
    isExceeded,
    isLow: !isExceeded && remainingSeconds <= Math.min(60, Math.ceil(limitSeconds * 0.2)),
    formatted: `${isExceeded ? '+' : ''}${formatTimer(Math.abs(remainingSeconds))}`,
    label: isExceeded ? 'Превышение' : 'Осталось',
  };
}

function answerFor(input: StudentCardInput, questionId: string): QuestionAnswer | undefined {
  return input.incident?.answers.find((answer) => answer.questionId === questionId);
}

function validateCard(
  input: StudentCardInput,
  form: StudentCardForm,
  calculation: CardCalculation | null,
): CardErrors {
  const errors: CardErrors = {};
  const selectedSigns = input.incident?.selectedSignIds ?? [];
  const missingInputIds = new Set(calculation?.missingInputIds ?? []);
  form.signGroups.forEach((group) => {
    if ((group.required || missingInputIds.has(group.id))
      && group.options.length > 0 && !selectedSigns[group.level - 1]) {
      errors[`sign-${group.level}`] = 'Выберите признак этого уровня.';
    }
  });
  form.questions.forEach((question) => {
    const answer = answerFor(input, question.id);
    const hasAnswer = question.inputType === 'TEXT'
      ? Boolean(answer?.freeText?.trim())
      : Boolean(answer?.optionIds?.length);
    if ((question.required || missingInputIds.has(question.id)) && !hasAnswer) {
      errors[`question-${question.id}`] = 'Ответьте на вопрос.';
    }
  });
  if (!input.address?.displayAddress.trim()) errors.address = 'Укажите адрес происшествия.';
  if (input.victims === null) errors.victims = 'Укажите, есть ли пострадавшие.';
  return errors;
}

function ReportView({
  report,
  elapsedSeconds,
  timeLimitExceeded,
}: {
  report: StudentSessionReport;
  elapsedSeconds: number;
  timeLimitExceeded: boolean;
}) {
  const passedCriteria = report.criteria.filter((criterion) => criterion.passed);

  return (
    <Stack className="student-report" gap="lg">
      {timeLimitExceeded && (
        <Alert color="red" icon={<IconClock size={18} />} title="Лимит времени превышен">
          Фактическая длительность: {formatTimer(elapsedSeconds)}. Нарушение сохранено в состоянии сессии.
        </Alert>
      )}
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
            Итоговая оценка и рекомендации получены от Core/AI.
          </Text>
          <Text size="sm" c="dimmed" mt={4}>Фактическая длительность: {formatTimer(elapsedSeconds)}</Text>
          <Progress
            value={report.maxScore ? (report.score / report.maxScore) * 100 : 0}
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
            <ThemeIcon color="teal" variant="light" radius="xl"><IconShieldCheck size={19} /></ThemeIcon>
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
          ) : <Text size="sm">Карточка совпадает с ожидаемым решением сценария.</Text>}
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
                <Text component="li" size="sm" c="dimmed" key={recommendation}>{recommendation}</Text>
              ))}
            </Stack>
          </div>
        </Group>
      </Paper>
    </Stack>
  );
}

const serviceStatusMeta: Record<ServiceStatus, { label: string; tone: string }> = {
  ADDED: { label: 'Назначена', tone: 'pending' },
  RECEIVED: { label: 'Получено', tone: 'active' },
  ACCEPTED: { label: 'Принято', tone: 'active' },
  RESPONDING: { label: 'Реагирует', tone: 'active' },
  ARRIVED: { label: 'На месте', tone: 'success' },
  COMPLETED: { label: 'Завершено', tone: 'success' },
  REFUSED: { label: 'Отказ', tone: 'danger' },
  FAILED: { label: 'Ошибка', tone: 'danger' },
};

function CalculationView({ calculation }: { calculation: CardCalculation | null }) {
  const color = !calculation ? 'gray'
    : calculation.status === 'RESOLVED' ? 'teal' : calculation.status === 'NO_MATCH' ? 'red' : 'blue';
  const statusLabel = !calculation ? 'Пусто'
    : calculation.status === 'RESOLVED'
      ? 'Рассчитано'
      : calculation.status === 'NO_MATCH' ? 'Ошибка' : 'Заполняется';
  return (
    <Paper className="calculation-panel" withBorder radius="lg" p="lg" aria-label="Вычисленные поля Core">
      <Group justify="space-between" align="flex-start" gap="md">
        <Group gap="sm" align="center" wrap="nowrap">
          <ThemeIcon variant="light" color={color}><IconRoute size={18} /></ThemeIcon>
          <div>
            <Text className="section-eyebrow">Только для чтения</Text>
            <Title order={3}>Результат Core</Title>
          </div>
        </Group>
        <Badge color={color} variant="light">{statusLabel}</Badge>
      </Group>
      {!calculation ? (
        <Text className="calculation-panel__placeholder" size="sm" c="dimmed">
          Выберите признаки справа — тип происшествия и службы появятся без ручного ввода.
        </Text>
      ) : (
        <div className="calculation-summary">
          <div>
            <Text size="xs" c="dimmed">Тип происшествия</Text>
            <Text fw={700}>{calculation.incidentType ?? 'Уточняется'}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">Код классификатора</Text>
            <Text fw={700}>{calculation.classifierCode ?? '—'}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">Службы ДДС</Text>
            <Text fw={700}>{calculation.services.length || '—'}</Text>
          </div>
        </div>
      )}
      {calculation && calculation.explanations.length > 0 && (
        <Stack component="ul" gap={4} className="calculation-explanations">
          {calculation.explanations.map((explanation) => (
            <Text component="li" size="xs" c="dimmed" key={explanation}>{explanation}</Text>
          ))}
        </Stack>
      )}
    </Paper>
  );
}

function DispatchStrip({
  calculation,
  assignments,
  submitted,
  error,
  isSubmitting,
}: {
  calculation: CardCalculation | null;
  assignments: ServiceAssignment[];
  submitted: boolean;
  error: string;
  isSubmitting: boolean;
}) {
  const phase = error ? 'error'
    : submitted ? 'sent'
      : calculation?.status === 'RESOLVED' ? 'calculated'
        : calculation ? 'filling' : 'empty';
  const phaseLabel = {
    empty: 'Пусто',
    filling: 'Заполняется',
    calculated: 'Рассчитано',
    sent: 'Отправлено',
    error: 'Ошибка',
  }[phase];
  const calculatedServices = assignments.length === 0 ? calculation?.services ?? [] : [];
  const hasServices = assignments.length > 0 || calculatedServices.length > 0;

  return (
    <footer className={`dispatch-strip dispatch-strip--${phase}`} aria-label="Рассчитанные службы ДДС">
      <div className="dispatch-strip__lead">
        <IconRoute size={18} aria-hidden="true" />
        <strong>Службы ДДС</strong>
        <span className="dispatch-strip__phase">{phaseLabel}</span>
      </div>
      <div className="dispatch-strip__services" role="list" aria-live="polite">
        {assignments.map((assignment) => {
          const status = assignment.overdue
            ? { label: 'Нет реагирования', tone: 'danger' }
            : serviceStatusMeta[assignment.status];
          return (
            <div
              className={`dispatch-service dispatch-service--${status.tone}`}
              key={assignment.id}
              role="listitem"
              aria-label={`${assignment.displayName}: ${status.label}`}
              title={`${assignment.displayName}: ${status.label}`}
            >
              <span className="dispatch-service__name">{assignment.displayName}</span>
              <span className="dispatch-service__status">{status.label}</span>
            </div>
          );
        })}
        {calculatedServices.map((service) => (
          <div
            className="dispatch-service dispatch-service--calculated"
            key={service.id}
            role="listitem"
            aria-label={`${service.displayName}: рассчитана Core`}
            title={service.reasons[0]?.message ?? 'Рассчитано Core'}
          >
            <span className="dispatch-service__name">{service.displayName}</span>
            <span className="dispatch-service__status">Рассчитана</span>
          </div>
        ))}
        {!hasServices && (
          <Text className="dispatch-strip__placeholder" size="xs" title={error || undefined}>
            {error ? 'Проверьте сообщение об ошибке в карточке.' : 'Службы появятся здесь после расчёта Core.'}
          </Text>
        )}
      </div>
      <div className="dispatch-strip__actions">
        {submitted ? (
          <Text size="xs">Карточка отправлена. Статусы служб доступны только для чтения.</Text>
        ) : (
          <>
            <Text size="xs">После отправки изменить карточку будет нельзя.</Text>
            <Button
              form="student-incident-form"
              type="submit"
              leftSection={<IconSend size={17} />}
              loading={isSubmitting}
            >
              Отправить на оценку
            </Button>
          </>
        )}
      </div>
    </footer>
  );
}

export function StudentPage({ api = studentApi }: { api?: StudentApi }) {
  const [assignment, setAssignment] = useState<StudentAssignment | null>(null);
  const [cardForm, setCardForm] = useState<StudentCardForm | null>(null);
  const [input, setInput] = useState<StudentCardInput | null>(null);
  const [calculation, setCalculation] = useState<CardCalculation | null>(null);
  const [report, setReport] = useState<StudentSessionReport | null>(null);
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  const [loadError, setLoadError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [errors, setErrors] = useState<CardErrors>({});
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serviceAssignments, setServiceAssignments] = useState<ServiceAssignment[]>([]);
  const [serviceAssignmentsError, setServiceAssignmentsError] = useState('');
  const [proposalStatus, setProposalStatus] = useState('');
  const [proposalBusy, setProposalBusy] = useState(false);
  const revisionRef = useRef(0);
  const changeIdRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const saveQueueRef = useRef<Promise<StudentSession | null>>(Promise.resolve(null));
  const lastSavedRef = useRef('');
  const lastEnqueuedRef = useRef('');
  const inputRef = useRef<StudentCardInput | null>(null);
  const calculationRef = useRef<CardCalculation | null>(null);

  const loadAssignment = useCallback(async () => {
    setLoadError('');
    setAssignment(null);
    setCardForm(null);
    setServiceAssignments([]);
    setServiceAssignmentsError('');
    try {
      const loaded = await api.getAssignment();
      const [formResult, assignmentsResult] = await Promise.allSettled([
        api.getCardForm(loaded.session.id),
        api.getServiceAssignments(loaded.session.id),
      ]);
      if (formResult.status === 'rejected') throw formResult.reason;
      const form = formResult.value;
      const loadedInput = loaded.session.card.input;
      setAssignment(loaded);
      setCardForm(form);
      setInput(loadedInput);
      inputRef.current = loadedInput;
      setCalculation(loaded.session.card.calculation);
      calculationRef.current = loaded.session.card.calculation;
      setReport(loaded.session.report);
      setCompletedAt(loaded.session.endedAt);
      revisionRef.current = loaded.session.cardRevision;
      lastSavedRef.current = JSON.stringify(loadedInput);
      lastEnqueuedRef.current = '';
      const hasDraft = loaded.session.cardRevision > 0;
      setSaveStatus(hasDraft ? 'saved' : 'idle');
      if (assignmentsResult.status === 'fulfilled') {
        setServiceAssignments(assignmentsResult.value);
      } else {
        setServiceAssignmentsError(getApiErrorMessage(
          assignmentsResult.reason,
          'Статусы служб ДДС временно недоступны.',
        ));
      }
    } catch (error) {
      setLoadError(getApiErrorMessage(error, 'Не удалось получить задание.'));
    }
  }, [api]);

  useEffect(() => {
    void loadAssignment();
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, [loadAssignment]);

  const timer = useSessionTimer(
    assignment?.session.startedAt,
    completedAt ?? assignment?.session.endedAt,
    assignment?.session.timeLimitSeconds ?? assignment?.scenario.timeLimitSeconds ?? 0,
    Boolean(report),
  );

  const saveStatusText = useMemo(() => ({
    idle: '',
    saving: 'Сохраняем черновик…',
    saved: 'Черновик сохранён',
    error: 'Не удалось сохранить черновик',
  }[saveStatus]), [saveStatus]);

  const enqueueSave = useCallback((snapshot: StudentCardInput, changeId: number) => {
    if (!assignment) return Promise.resolve(null);
    const serialized = JSON.stringify(snapshot);
    if (serialized === lastSavedRef.current) {
      if (changeId === changeIdRef.current) setSaveStatus('saved');
      return saveQueueRef.current;
    }
    if (serialized === lastEnqueuedRef.current) return saveQueueRef.current;
    lastEnqueuedRef.current = serialized;
    const operation = saveQueueRef.current.catch(() => null).then(async () => {
      const session = await api.saveCard(assignment.session.id, snapshot, revisionRef.current);
      revisionRef.current = session.cardRevision;
      lastSavedRef.current = serialized;
      if (changeId === changeIdRef.current) {
        calculationRef.current = session.card.calculation;
        setCalculation(session.card.calculation);
        setAssignment((current) => current ? { ...current, session } : current);
        try {
          const nextForm = await api.getCardForm(session.id);
          setCardForm(nextForm);
        } catch (error) {
          setSubmitError(getApiErrorMessage(error, 'Черновик сохранён, но форму уточнений обновить не удалось.'));
        }
        setSaveStatus('saved');
      }
      return session;
    }).catch((error: unknown) => {
      if (lastEnqueuedRef.current === serialized) lastEnqueuedRef.current = '';
      if (changeId === changeIdRef.current) {
        setSaveStatus('error');
        setSubmitError(getApiErrorMessage(error, 'Не удалось сохранить черновик.'));
      }
      throw error;
    });
    saveQueueRef.current = operation;
    return operation;
  }, [api, assignment]);

  function updateInput(nextInput: StudentCardInput, clearedErrors: string[] = []) {
    inputRef.current = nextInput;
    setInput(nextInput);
    setErrors((current) => {
      const next = { ...current };
      clearedErrors.forEach((field) => { next[field] = undefined; });
      return next;
    });
    setSubmitError('');
    setSaveStatus('saving');
    const changeId = ++changeIdRef.current;
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      void enqueueSave(nextInput, changeId).catch(() => undefined);
    }, 300);
  }

  async function flushDraft() {
    if (!inputRef.current) return null;
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    return enqueueSave(inputRef.current, changeIdRef.current);
  }

  function updateSigns(level: 1 | 2 | 3, value: string | null) {
    if (!input) return;
    const selected = [...(input.incident?.selectedSignIds ?? [])].slice(0, level - 1);
    if (value) selected.push(value);
    updateInput({
      ...input,
      incident: { selectedSignIds: selected, answers: [] },
    }, [`sign-${level}`, ...cardForm?.questions.map((question) => `question-${question.id}`) ?? []]);
  }

  function updateQuestion(questionId: string, nextAnswer: QuestionAnswer) {
    if (!input) return;
    const answers = (input.incident?.answers ?? []).filter((answer) => answer.questionId !== questionId);
    if ((nextAnswer.optionIds?.length ?? 0) > 0 || Boolean(nextAnswer.freeText?.trim())) {
      answers.push(nextAnswer);
    }
    updateInput({
      ...input,
      incident: {
        selectedSignIds: input.incident?.selectedSignIds ?? [],
        answers,
      },
    }, [`question-${questionId}`]);
  }

  async function submitCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment || !input || !cardForm) return;
    const nextErrors = validateCard(input, cardForm, calculationRef.current);
    setErrors(nextErrors);
    setSubmitError('');
    if (Object.keys(nextErrors).length > 0) {
      setSubmitError('Заполните обязательные поля перед отправкой карточки.');
      return;
    }

    setIsSubmitting(true);
    try {
      await flushDraft();
      const currentCalculation = calculationRef.current;
      if (!currentCalculation || currentCalculation.status !== 'RESOLVED'
        || currentCalculation.missingInputIds.length > 0) {
        throw new Error('Core ещё не завершил расчёт. Проверьте признаки и дополнительные вопросы.');
      }
      const result = await api.submitCard(assignment.session.id, inputRef.current!, revisionRef.current);
      setReport(result);
      setCompletedAt(new Date().toISOString());
      try {
        setServiceAssignments(await api.getServiceAssignments(assignment.session.id));
        setServiceAssignmentsError('');
      } catch (assignmentsError) {
        setServiceAssignmentsError(getApiErrorMessage(
          assignmentsError,
          'Карточка отправлена, но статусы служб ДДС временно недоступны.',
        ));
      }
    } catch (error) {
      setSubmitError(getApiErrorMessage(
        error,
        error instanceof Error ? error.message : 'Не удалось отправить карточку. Данные сохранены — попробуйте ещё раз.',
      ));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loadError) {
    return <Stack gap="md">
      {secureAuth && <TrainingHistoryPanel role="student" />}
      <ErrorState title="Не удалось получить задание" description={loadError} onRetry={() => void loadAssignment()} />
    </Stack>;
  }

  if (!assignment || !input || !cardForm) {
    return <LoadingState title="Получаем задание" description="Подготавливаем сценарий и карточку происшествия." />;
  }

  const selectedSigns = input.incident?.selectedSignIds ?? [];
  const caller = input.caller ?? emptyCaller;
  const phone = caller.phoneNumbers[0]?.value ?? '';
  const timeLimitExceeded = timer.isExceeded || assignment.session.timeLimitExceeded;

  return (
    <Stack className="student-page" gap="md">
      {secureAuth && <TrainingHistoryPanel role="student" />}
      <Paper className="assignment-brief" withBorder radius="sm" p="md">
        <div className="assignment-brief__main">
          <Text className="page-eyebrow">Учебная сессия · классификатор {cardForm.classifierVersion}</Text>
          <Title order={1}>{report ? 'Результат задания' : 'Моё задание'}</Title>
          {!report && <Title className="assignment-brief__scenario" order={2}>{assignment.scenario.title}</Title>}
          <Text className="assignment-brief__profile" size="sm">
            {report ? 'Изучите разбор, сформированный Core/AI.' : assignment.scenario.profile}
          </Text>
        </div>
        <div className="assignment-brief__meta">
          <div className="assignment-id">
            <Text size="xs" c="dimmed">ID сессии / карточки</Text>
            <Text className="assignment-id__value" title={assignment.session.id}>{assignment.session.id}</Text>
          </div>
          <div className={`assignment-timer${timer.isLow ? ' assignment-timer--low' : ''}${timeLimitExceeded ? ' assignment-timer--exceeded' : ''}`}>
            <IconClock size={19} stroke={1.8} aria-hidden="true" />
            <div>
              <Text size="xs">{timeLimitExceeded ? 'Превышение' : timer.label}</Text>
              <Text className="assignment-timer__value" data-testid="assignment-timer">{timer.formatted}</Text>
            </div>
          </div>
          {!report && saveStatus !== 'idle' && (
            <Group className={`save-indicator save-indicator--${saveStatus}`} gap={6} wrap="nowrap">
              <IconDeviceFloppy size={15} aria-hidden="true" />
              <Text size="xs">{saveStatusText}</Text>
            </Group>
          )}
        </div>
      </Paper>

      <>
        <Paper
          id="student-incident-form"
          component="form"
          className="incident-form"
          withBorder
          radius="sm"
          p={0}
          onSubmit={submitCard}
          noValidate
        >
          <div className="incident-form__heading">
            <Title order={2}>Карточка происшествия</Title>
            <Text size="xs">Поля со звёздочкой обязательны. Выводы Core недоступны для редактирования.</Text>
          </div>
          {submitError && (
            <Alert color="red" icon={<IconAlertCircle size={18} />} withCloseButton onClose={() => setSubmitError('')}>
              {submitError}
            </Alert>
          )}

          <fieldset className="incident-form__workspace" disabled={Boolean(report)}>
            <div className="incident-form__column incident-form__column--left">
          <section className="card-section" aria-labelledby="details-heading">
            <div>
              <Text className="section-eyebrow">Данные звонка</Text>
              <Title id="details-heading" order={3}>Заявитель</Title>
            </div>
            <div className="incident-form__grid incident-form__grid--three">
              <TextInput
                label="ФИО заявителя"
                placeholder="Необязательно"
                value={caller.fullName ?? ''}
                onChange={(event) => updateInput({
                  ...input,
                  caller: { ...caller, fullName: event.currentTarget.value || null },
                })}
              />
              <TextInput
                label="Телефон заявителя"
                placeholder="+7 900 000-00-00"
                type="tel"
                value={phone}
                onChange={(event) => updateInput({
                  ...input,
                  caller: {
                    ...caller,
                    phoneNumbers: event.currentTarget.value
                      ? [{ value: event.currentTarget.value, kind: 'PROVIDED', foreign: false }]
                      : [],
                  },
                })}
              />
              <Select
                label="Статус заявителя"
                placeholder="Выберите статус"
                clearable
                data={[
                  { value: 'EYEWITNESS', label: 'Очевидец' },
                  { value: 'VICTIM', label: 'Пострадавший' },
                  { value: 'RELATIVE', label: 'Родственник' },
                  { value: 'ACQUAINTANCE', label: 'Знакомый' },
                  { value: 'CHILD', label: 'Ребёнок' },
                  { value: 'PARTICIPANT', label: 'Участник' },
                  { value: 'OTHER', label: 'Другое' },
                ]}
                value={caller.status}
                onChange={(value) => updateInput({
                  ...input,
                  caller: { ...caller, status: value as CallerInput['status'] },
                })}
              />
            </div>
          </section>

          <section className="card-section" aria-labelledby="address-heading">
            <div>
              <Text className="section-eyebrow">Место вызова</Text>
              <Title id="address-heading" order={3}>Адрес происшествия</Title>
              <Text size="sm" c="dimmed">Адрес сохраняется и строкой для отображения, и отдельными структурированными полями.</Text>
            </div>
            <TextInput
              label="Адрес одной строкой"
              placeholder="Город, улица, дом, корпус, квартира"
              value={input.address?.displayAddress ?? ''}
              onChange={(event) => updateInput({
                ...input,
                address: { ...(input.address ?? { displayAddress: '' }), displayAddress: event.currentTarget.value },
              }, ['address'])}
              error={errors.address}
              required
            />
            <div className="structured-address-grid">
              {([
                ['region', 'Регион'],
                ['locality', 'Населённый пункт'],
                ['street', 'Улица'],
                ['house', 'Дом'],
                ['building', 'Корпус / строение'],
                ['apartment', 'Квартира / помещение'],
              ] as const).map(([field, label]) => (
                <TextInput
                  key={field}
                  label={label}
                  value={input.address?.[field] ?? ''}
                  onChange={(event) => updateInput({
                    ...input,
                    address: {
                      ...(input.address ?? { displayAddress: '' }),
                      [field]: event.currentTarget.value || null,
                    },
                  })}
                />
              ))}
            </div>
          </section>

          <section className="card-section" aria-labelledby="description-heading">
            <div>
              <Text className="section-eyebrow">Обстоятельства</Text>
              <Title id="description-heading" order={3}>Описание происшествия</Title>
            </div>
            <Textarea
              label="Описание со слов заявителя"
              description="Фиксируйте наблюдаемые факты, не подменяя ими тип происшествия."
              placeholder="Что произошло, какие угрозы наблюдает заявитель"
              minRows={4}
              value={input.description ?? ''}
              onChange={(event) => updateInput({ ...input, description: event.currentTarget.value })}
            />
          </section>

          <section className="card-section" aria-labelledby="victims-heading">
            <div>
              <Text className="section-eyebrow">Сведения</Text>
              <Title id="victims-heading" order={3}>Пострадавшие</Title>
            </div>
            <Radio.Group
              label="Есть пострадавшие?"
              value={input.victims === null ? '' : input.victims.present ? 'yes' : 'no'}
              onChange={(value) => updateInput({
                ...input,
                victims: { present: value === 'yes', count: null, threatToPeople: null },
              }, ['victims'])}
              error={errors.victims}
              required
            >
              <Group mt="xs"><Radio value="yes" label="Да" /><Radio value="no" label="Нет" /></Group>
            </Radio.Group>
            {input.victims?.present && (
              <div className="incident-form__grid">
                <NumberInput
                  label="Количество пострадавших"
                  min={0}
                  value={input.victims.count ?? ''}
                  onChange={(value) => updateInput({
                    ...input,
                    victims: { ...input.victims!, count: typeof value === 'number' ? value : null },
                  })}
                />
                <Radio.Group
                  label="Есть угроза людям?"
                  value={input.victims.threatToPeople === null || input.victims.threatToPeople === undefined
                    ? '' : input.victims.threatToPeople ? 'yes' : 'no'}
                  onChange={(value) => updateInput({
                    ...input,
                    victims: { ...input.victims!, threatToPeople: value === 'yes' },
                  })}
                >
                  <Group mt="xs"><Radio value="yes" label="Да" /><Radio value="no" label="Нет" /></Group>
                </Radio.Group>
              </div>
            )}
          </section>
            </div>
            <div className="incident-form__column incident-form__column--right">
              <CalculationView calculation={calculation} />
          <section className="card-section" aria-labelledby="signs-heading">
            <div>
              <Text className="section-eyebrow">Классификация</Text>
              <Title id="signs-heading" order={3}>Признаки происшествия</Title>
              <Text size="sm" c="dimmed">Каждый выбор запрашивает у Core следующий доступный уровень.</Text>
            </div>
            <div className="incident-form__grid incident-form__grid--three">
              {cardForm.signGroups.map((group) => (
                <Select
                  key={group.id}
                  label={`${group.level}. ${group.label}`}
                  placeholder={group.options.length ? 'Выберите признак' : 'Сначала заполните предыдущий уровень'}
                  data={group.options.map((option) => ({ value: option.id, label: option.label }))}
                  value={selectedSigns[group.level - 1] ?? null}
                  onChange={(value) => updateSigns(group.level, value)}
                  error={errors[`sign-${group.level}`]}
                  required={group.required}
                  disabled={group.level > 1 && group.options.length === 0}
                  searchable
                  clearable
                />
              ))}
            </div>
          </section>

          {cardForm.questions.length > 0 && (
            <section className="card-section" aria-labelledby="questions-heading">
              <div>
                <Text className="section-eyebrow">Уточнения</Text>
                <Title id="questions-heading" order={3}>Дополнительные вопросы</Title>
                <Text size="sm" c="dimmed">Набор вопросов зависит от выбранного пути признаков.</Text>
              </div>
              <div className="question-grid">
                {cardForm.questions.map((question) => {
                  const answer = answerFor(input, question.id);
                  const error = errors[`question-${question.id}`];
                  const required = question.required || calculation?.missingInputIds.includes(question.id) === true;
                  if (question.inputType === 'TEXT') {
                    return (
                      <Textarea
                        key={question.id}
                        label={question.label}
                        value={answer?.freeText ?? ''}
                        onChange={(event) => updateQuestion(question.id, {
                          questionId: question.id,
                          freeText: event.currentTarget.value,
                        })}
                        error={error}
                        required={required}
                      />
                    );
                  }
                  if (question.inputType === 'MULTI_SELECT') {
                    return (
                      <div className="question-card" key={question.id}>
                        <Text size="sm" fw={500}>{question.label}</Text>
                        <Checkbox.Group
                          value={answer?.optionIds ?? []}
                          onChange={(optionIds) => updateQuestion(question.id, { questionId: question.id, optionIds })}
                        >
                          <Stack gap="xs" mt="xs">
                            {question.options.map((option) => (
                              <Checkbox key={option.id} value={option.id} label={option.label} />
                            ))}
                          </Stack>
                        </Checkbox.Group>
                        {error && <Text c="red" size="xs" mt={6}>{error}</Text>}
                      </div>
                    );
                  }
                  if (question.options.length > 2) {
                    return (
                      <Select
                        key={question.id}
                        label={question.label}
                        data={question.options.map((option) => ({ value: option.id, label: option.label }))}
                        value={answer?.optionIds?.[0] ?? null}
                        onChange={(value) => updateQuestion(question.id, {
                          questionId: question.id,
                          optionIds: value ? [value] : [],
                        })}
                        error={error}
                        required={required}
                      />
                    );
                  }
                  return (
                    <div className="question-card" key={question.id}>
                      <Radio.Group
                        label={question.label}
                        value={answer?.optionIds?.[0] ?? ''}
                        onChange={(value) => updateQuestion(question.id, { questionId: question.id, optionIds: [value] })}
                        error={error}
                        required={required}
                      >
                        <Group mt="xs">
                          {question.options.map((option) => <Radio key={option.id} value={option.id} label={option.label} />)}
                        </Group>
                      </Radio.Group>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
            </div>
          </fieldset>

        </Paper>
        {report && (
          <>
            <ReportView report={report} elapsedSeconds={timer.elapsedSeconds} timeLimitExceeded={timeLimitExceeded} />
            {secureAuth && <Paper withBorder radius="lg" p="md">
              <Text fw={600}>Предложить учебный вариант</Text>
              <Text size="sm" c="dimmed">Core перенесёт только признаки и варианты ответов из оценённой карточки. ФИО, телефон, адрес и свободный текст не попадут в сценарий. Преподаватель проверит его перед назначением.</Text>
              {proposalStatus && <Text size="sm" role="status" mt="sm">{proposalStatus}</Text>}
              <Button mt="sm" variant="light" loading={proposalBusy} onClick={() => {
                setProposalBusy(true); setProposalStatus('');
                void createHttpClient(apiConfig.baseUrl).request('/api/student/scenario-proposals', {
                  method: 'POST', body: { sessionId: assignment.session.id },
                }).then(() => setProposalStatus('Предложение отправлено преподавателю на проверку.'))
                  .catch((cause) => setProposalStatus(getApiErrorMessage(cause, 'Не удалось предложить карточку.')))
                  .finally(() => setProposalBusy(false));
              }}>Предложить преподавателю</Button>
            </Paper>}
          </>
        )}
      </>
      <DispatchStrip
        calculation={calculation}
        assignments={serviceAssignments}
        submitted={Boolean(report)}
        error={serviceAssignmentsError || submitError}
        isSubmitting={isSubmitting}
      />
    </Stack>
  );
}
