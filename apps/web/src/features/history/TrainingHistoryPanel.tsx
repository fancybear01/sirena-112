import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Button, Group, NumberInput, Paper, Stack, Text, Textarea, Title } from '@mantine/core';
import { apiConfig } from '../../api/config';
import { createHttpClient } from '../../api/httpClient';
import { getApiErrorMessage } from '../../api/errors';
import type { SessionReport } from '../../api/types';

type Feedback = {
  id: string;
  authorId: string;
  kind: 'COMMENT' | 'CORRECTION';
  text: string;
  createdAt: string;
  oldScore: number | null;
  newScore: number | null;
};

type Attempt = {
  sessionId: string;
  studentName: string | null;
  scenarioTitle: string;
  scenarioProfile: string;
  scenarioVersion: number;
  state: string;
  createdAt: string;
  elapsedSeconds: number | null;
  timeLimitSeconds: number;
  exceededLimit: boolean | null;
  comparison: {
    expectedClassifierCode: string;
    actualClassifierCode: string | null;
    classifierMatches: boolean;
    expectedServiceIds: string[];
    actualServiceIds: string[];
    servicesMatch: boolean;
    expectedAnswers: Record<string, string[]>;
    actualAnswers: Record<string, string[]>;
    answersMatch: boolean;
    finalTranscript: string[];
  } | null;
  originalReport: SessionReport | null;
  effectiveScore: number | null;
  feedback: Feedback[];
};

type History = {
  summary: { assigned: number; completed: number; averagePercent: number | null };
  attempts: Attempt[];
};

const sessionStateLabels: Record<string, string> = {
  CREATED: 'Создано', READY: 'Готово', RINGING: 'Вызов', ACTIVE: 'Идёт занятие', COMPLETED: 'Завершено',
  SCORING: 'Оценивается', SCORED: 'Оценено', FAILED: 'Ошибка',
};

function dateTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU');
}

export function TrainingHistoryPanel({ role }: { role: 'teacher' | 'student' }) {
  const http = useMemo(() => createHttpClient(apiConfig.baseUrl), []);
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [comment, setComment] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<Record<string, string>>({});
  const [newScore, setNewScore] = useState<Record<string, number | string>>({});

  const load = useCallback(async () => {
    try {
      setError('');
      setHistory(await http.request<History>(`/api/${role}/history`));
    } catch (cause) {
      setError(getApiErrorMessage(cause, 'Не удалось загрузить историю обучения.'));
    }
  }, [http, role]);

  useEffect(() => { void load(); }, [load]);

  async function send(id: string, path: 'comments' | 'corrections', body: object) {
    try {
      setBusyId(id);
      setError('');
      await http.request(`/api/teacher/history/${encodeURIComponent(id)}/${path}`, { method: 'POST', body });
      await load();
      if (path === 'comments') setComment((current) => ({ ...current, [id]: '' }));
      else setReason((current) => ({ ...current, [id]: '' }));
    } catch (cause) {
      setError(getApiErrorMessage(cause, 'Не удалось сохранить обратную связь.'));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="training-history" aria-label="История обучения" aria-busy={!history || Boolean(busyId)}>
      <Group className="history-header" justify="space-between"><Title order={2}>История обучения</Title><Button variant="subtle" onClick={() => void load()}>Обновить</Button></Group>
      {error && <Alert color="red" role="alert" mt="sm">{error}</Alert>}
      {!history ? <Text mt="sm" role="status" aria-live="polite">Загружаем историю…</Text> : (
        <Stack mt="md">
          <Text>Назначено: {history.summary.assigned}. Оценено: {history.summary.completed}. Средний результат: {history.summary.averagePercent === null ? '—' : `${history.summary.averagePercent.toFixed(1)}%`}.</Text>
          {history.attempts.length === 0 && <Text c="dimmed">Попыток пока нет.</Text>}
          {history.attempts.map((attempt) => (
            <Paper className="history-attempt" key={attempt.sessionId} withBorder p="md">
              <Group className="history-attempt__header" justify="space-between" align="flex-start">
                <div><Text fw={700}>{attempt.scenarioTitle} · версия {attempt.scenarioVersion}</Text>
                  <Text size="sm">{attempt.scenarioProfile}</Text>
                  <Text size="sm" c="dimmed">{role === 'teacher' && `${attempt.studentName ?? 'Без обучающегося'} · `}{dateTime(attempt.createdAt)} · {sessionStateLabels[attempt.state] ?? attempt.state}</Text></div>
                {attempt.originalReport && <Badge color={attempt.originalReport.passed ? 'teal' : 'orange'}>{attempt.effectiveScore} / {attempt.originalReport.maxScore}</Badge>}
              </Group>
              <Text size="sm" mt="xs">Время: {attempt.elapsedSeconds === null ? 'ещё не завершено' : `${attempt.elapsedSeconds} с`} / норматив {attempt.timeLimitSeconds} с{attempt.exceededLimit ? ' · превышен' : ''}</Text>
              {attempt.originalReport && (
                <Stack gap="xs" mt="sm">
                  {attempt.comparison && <>
                    <Text size="sm">Эталон классификатора: {attempt.comparison.expectedClassifierCode}; результат: {attempt.comparison.actualClassifierCode ?? 'не определён'} · {attempt.comparison.classifierMatches ? 'совпадает' : 'расхождение'}</Text>
                    <Text size="sm">Службы: эталон {attempt.comparison.expectedServiceIds.join(', ') || 'нет'}; результат {attempt.comparison.actualServiceIds.join(', ') || 'нет'} · {attempt.comparison.servicesMatch ? 'совпадают' : 'расхождение'}</Text>
                    <Text size="sm">Ответы по вопросам: {attempt.comparison.answersMatch ? 'совпадают с эталоном' : 'есть расхождения'}</Text>
                    {attempt.comparison.finalTranscript.map((part, index) => <Text key={index} size="sm">Расшифровка: {part}</Text>)}
                  </>}
                  <Text size="sm">Исходная оценка: {attempt.originalReport.score} / {attempt.originalReport.maxScore} (не изменяется)</Text>
                  {attempt.originalReport.criteria.map((criterion) => <Text key={criterion.code} size="sm">{criterion.passed ? '✓' : '✗'} {criterion.code}: {criterion.points}/{criterion.maxPoints} — {criterion.message}</Text>)}
                  {attempt.originalReport.errors.map((item, index) => <Text key={`${item.code}-${index}`} size="sm" c="red">{item.code}: {item.message}</Text>)}
                  {attempt.originalReport.recommendations.map((item, index) => <Text key={index} size="sm">Рекомендация: {item}</Text>)}
                </Stack>
              )}
              {attempt.feedback.map((item) => <Text key={item.id} size="sm" mt="xs">{dateTime(item.createdAt)} · {item.kind === 'COMMENT' ? 'Комментарий' : `Экспертная правка ${item.oldScore} → ${item.newScore}`}: {item.text}</Text>)}
              {role === 'teacher' && (
                <Stack mt="md" gap="xs">
                  <Textarea label="Комментарий обучающемуся" value={comment[attempt.sessionId] ?? ''}
                    onChange={(event) => { const value = event.currentTarget.value;
                      setComment((current) => ({ ...current, [attempt.sessionId]: value })); }} />
                  <Button size="xs" variant="light" disabled={!comment[attempt.sessionId]?.trim()} loading={busyId === attempt.sessionId}
                    onClick={() => void send(attempt.sessionId, 'comments', { text: comment[attempt.sessionId] })}>Добавить комментарий</Button>
                  {attempt.originalReport && <Group className="history-correction" align="end">
                    <NumberInput label="Экспертная оценка" min={0} max={attempt.originalReport.maxScore} value={newScore[attempt.sessionId] ?? ''}
                      onChange={(value) => setNewScore((current) => ({ ...current, [attempt.sessionId]: value }))} />
                    <Textarea label="Причина правки" value={reason[attempt.sessionId] ?? ''}
                      onChange={(event) => { const value = event.currentTarget.value;
                        setReason((current) => ({ ...current, [attempt.sessionId]: value })); }} />
                    <Button size="xs" variant="light" disabled={typeof newScore[attempt.sessionId] !== 'number' || (reason[attempt.sessionId]?.trim().length ?? 0) < 5}
                      loading={busyId === attempt.sessionId} onClick={() => void send(attempt.sessionId, 'corrections',
                        { newScore: newScore[attempt.sessionId], reason: reason[attempt.sessionId] })}>Сохранить правку</Button>
                  </Group>}
                </Stack>
              )}
            </Paper>
          ))}
        </Stack>
      )}
    </section>
  );
}
