import { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, NumberInput, Paper, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import { authApi } from '../../api/auth';
import { apiConfig } from '../../api/config';
import { getApiErrorMessage } from '../../api/errors';
import { createHttpClient } from '../../api/httpClient';
import { scenarioCategories, type ScenarioCategory, type ScenarioDifficulty } from '../../api/types';
import { getScenarioCategoryLabel } from '../../api/scenarioLabels';

type Workflow = {
  id: string; familyId: string; version: number; revision: number; status: 'DRAFT' | 'APPROVED';
  scenario: Record<string, unknown>; comment: string; source: 'MANUAL' | 'AI' | 'COPY' | 'STUDENT';
};
type Student = { id: string; username: string; displayName: string };
type SourceScenario = Record<string, unknown> & { id: string; title: string };
const http = createHttpClient(apiConfig.baseUrl);
const difficultyOptions = [
  { value: 'BASIC', label: 'Базовая' },
  { value: 'INTERMEDIATE', label: 'Средняя' },
  { value: 'ADVANCED', label: 'Высокая' },
];
const workflowStatusLabels: Record<Workflow['status'], string> = { DRAFT: 'Черновик', APPROVED: 'Утверждён' };
const workflowSourceLabels: Record<Workflow['source'], string> = {
  MANUAL: 'Вручную', AI: 'AI', COPY: 'Копия', STUDENT: 'Предложение обучающегося',
};

export function ScenarioWorkflowPanel({ onApproved }: { onApproved: () => void }) {
  const [items, setItems] = useState<Workflow[]>([]);
  const [sources, setSources] = useState<SourceScenario[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState('');
  const [comment, setComment] = useState('');
  const [category, setCategory] = useState<ScenarioCategory>('FIRE');
  const [difficulty, setDifficulty] = useState<ScenarioDifficulty>('BASIC');
  const [seed, setSeed] = useState<number | string>(0);
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [myGroupId, setMyGroupId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const selected = items.find((item) => item.id === selectedId);

  const reload = useCallback(async () => {
    const [workflows, approved, groupStudents, me] = await Promise.all([
      http.request<Workflow[]>('/api/teacher/scenarios/workflow'),
      http.request<SourceScenario[]>('/api/teacher/scenarios'),
      http.request<Student[]>('/api/teacher/students'),
      authApi.me(),
    ]);
    setItems(workflows);
    setSources(approved);
    setSourceId((current) => current ?? approved[0]?.id ?? null);
    setStudents(groupStudents);
    setStudentId((current) => current ?? groupStudents[0]?.id ?? null);
    setMyGroupId(me.groupId);
  }, []);

  useEffect(() => {
    void reload()
      .catch((cause) => setError(getApiErrorMessage(cause, 'Не удалось загрузить сценарии.')))
      .finally(() => setLoading(false));
  }, [reload]);

  function choose(id: string | null, list = items) {
    setSelectedId(id);
    const item = list.find((entry) => entry.id === id);
    setEditor(item ? JSON.stringify(item.scenario, null, 2) : '');
    setComment(item?.comment ?? '');
    setMessage('');
  }

  async function perform(action: () => Promise<Workflow | void>, success: string) {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await action();
      const fresh = await http.request<Workflow[]>('/api/teacher/scenarios/workflow');
      setItems(fresh);
      if (result?.id) choose(result.id, fresh);
      else if (selectedId) choose(selectedId, fresh);
      setMessage(success);
    } catch (cause) {
      setError(cause instanceof Error && cause.name !== 'ApiError' ? cause.message
        : getApiErrorMessage(cause, 'Операция не выполнена.'));
    } finally { setBusy(false); }
  }

  function parseEditor(): Record<string, unknown> {
    const value: unknown = JSON.parse(editor);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Нужен JSON-объект сценария');
    return value as Record<string, unknown>;
  }

  return <Paper className="scenario-workflow" withBorder radius="lg" p="xl" aria-busy={loading || busy}>
    <Stack gap="md">
      <div><Title order={2}>Создание и назначение сценариев</Title>
        <Text c="dimmed" size="sm">Эталон проверяется по официальному классификатору перед утверждением. Активную версию изменить нельзя.</Text></div>
      {error && <Alert color="red" role="alert">{error}</Alert>}
      {message && <Alert color="teal" role="status" aria-live="polite">{message}</Alert>}
      {loading && <Text role="status" aria-live="polite">Загружаем версии сценариев…</Text>}
      <Group className="workflow-controls" align="end">
        <Select label="Категория для AI" searchable value={category} onChange={(value) => value && setCategory(value as ScenarioCategory)}
          data={scenarioCategories.map((value) => ({ value, label: getScenarioCategoryLabel(value) }))} disabled={loading || busy} />
        <Select label="Сложность" value={difficulty} onChange={(value) => value && setDifficulty(value as ScenarioDifficulty)}
          data={difficultyOptions} disabled={loading || busy} />
        <NumberInput className="workflow-seed" label="Вариант" min={0} value={seed} onChange={setSeed} disabled={loading || busy} />
        <Button loading={busy} onClick={() => void perform(() => http.request<Workflow>('/api/teacher/scenarios/workflow/drafts/generate', {
          method: 'POST', body: { category, difficulty, seed: Number(seed) || 0 },
        }), 'AI предложил черновик. Проверьте и утвердите его.')}>Получить черновик от AI</Button>
      </Group>
      <Group className="workflow-controls" align="end">
        <Select className="workflow-source" label="Готовый сценарий для копии" searchable value={sourceId} onChange={setSourceId}
          data={sources.map((item) => ({ value: item.id, label: item.title }))} disabled={loading || busy} />
        <Button variant="light" disabled={!sourceId} loading={busy} onClick={() => void perform(() => {
          const source = sources.find((item) => item.id === sourceId);
          if (!source) throw new Error('Выберите сценарий');
          return http.request<Workflow>('/api/teacher/scenarios/workflow/drafts', {
            method: 'POST', body: { scenario: source, comment: 'Черновик на основе готового сценария' },
          });
        }, 'Создан новый черновик.')}>Создать черновик-копию</Button>
      </Group>
      <Select label="Версия в работе" searchable value={selectedId} onChange={(id) => choose(id)}
        data={items.map((item) => ({ value: item.id, label: `${item.scenario.title ?? item.id} · версия ${item.version} · ${workflowStatusLabels[item.status]}` }))}
        disabled={loading || busy} />
      {selected && <>
        <Group><Badge color={selected.status === 'APPROVED' ? 'teal' : 'orange'}>{workflowStatusLabels[selected.status]}</Badge>
          <Text size="sm">Версия {selected.version}, ревизия {selected.revision}, источник: {workflowSourceLabels[selected.source]}</Text></Group>
        <Textarea label="Сценарий и эталон (JSON)" description="Можно исправить название, профиль, норматив, признаки, ответы и критерии. Службы должны соответствовать классификатору."
          autosize minRows={10} maxRows={22} value={editor} onChange={(event) => setEditor(event.currentTarget.value)}
          readOnly={selected.status !== 'DRAFT'} />
        <Textarea label="Комментарий преподавателя" value={comment} onChange={(event) => setComment(event.currentTarget.value)}
          readOnly={selected.status !== 'DRAFT'} />
        <Group className="workflow-actions">
          {selected.status === 'DRAFT' ? <>
            <Button loading={busy} onClick={() => void perform(() => http.request<Workflow>(`/api/teacher/scenarios/workflow/${selected.id}`, {
              method: 'PUT', body: { scenario: parseEditor(), comment, expectedRevision: selected.revision },
            }), 'Черновик сохранён.')}>Сохранить правки</Button>
            <Button loading={busy} variant="light" onClick={() => void perform(async () => {
              const result = await http.request<{ valid: boolean; errors: string[] }>(`/api/teacher/scenarios/workflow/${selected.id}/validate`, { method: 'POST' });
              if (!result.valid) throw new Error(result.errors.join('; '));
            }, 'Эталон и структура сценария корректны.')}>Проверить эталон</Button>
            <Button loading={busy} color="teal" onClick={() => void perform(async () => {
              const result = await http.request<Workflow>(`/api/teacher/scenarios/workflow/${selected.id}/approve?expectedRevision=${selected.revision}`, { method: 'POST' });
              onApproved();
              return result;
            }, 'Версия утверждена и доступна для назначения.')}>Утвердить</Button>
          </> : <Button loading={busy} variant="light" onClick={() => void perform(() => http.request<Workflow>(
            `/api/teacher/scenarios/workflow/${selected.id}/fork`, { method: 'POST' }), 'Создана новая версия-черновик.')}>Новая версия</Button>}
        </Group>
        {selected.status === 'APPROVED' && <Group className="workflow-controls" align="end">
          <Select label="Студент группы" value={studentId} onChange={setStudentId}
            data={students.map((student) => ({ value: student.id, label: `${student.displayName} (${student.username})` }))} />
          <Button loading={busy} disabled={!studentId} onClick={() => void perform(async () => {
            await http.request(`/api/teacher/scenarios/workflow/${selected.id}/assign`, {
              method: 'POST', body: { studentId },
            });
          }, 'Занятие назначено студенту.')}>Назначить студенту</Button>
          <Button loading={busy} variant="light" disabled={!myGroupId} onClick={() => void perform(async () => {
            await http.request(`/api/teacher/scenarios/workflow/${selected.id}/assign`, {
              method: 'POST', body: { groupId: myGroupId },
            });
          }, 'Занятия назначены всей группе.')}>Назначить группе</Button>
        </Group>}
      </>}
      <Text size="xs" c="dimmed">Предложения студентов из оценённых карточек появляются в этом списке как черновики. Преподаватель проверяет эталон и решает, утверждать ли их.</Text>
    </Stack>
  </Paper>;
}
