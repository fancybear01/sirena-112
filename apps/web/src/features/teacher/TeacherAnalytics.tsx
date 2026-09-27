import type { CSSProperties } from 'react';
import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text, Title } from '@mantine/core';
import { IconAlertCircle, IconChartHistogram, IconInbox } from '@tabler/icons-react';
import type { TeacherAnalyticsSummary } from './api/types';

type TeacherAnalyticsProps = {
  summary: TeacherAnalyticsSummary | null;
  error: string;
  onRetry: () => void;
};

function formatDay(day: string) {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return day;
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    timeZone: 'UTC',
  }).format(parsed);
}

function formatPercent(value: number | null) {
  if (value === null) return '—';
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)}%`;
}

function getPeriod(summary: TeacherAnalyticsSummary | null) {
  if (!summary) return errorPeriod;
  if (summary.daily.length === 0) return 'нет данных';
  const first = formatDay(summary.daily[0].day);
  const last = formatDay(summary.daily[summary.daily.length - 1].day);
  return first === last ? first : `${first} — ${last}`;
}

const errorPeriod = 'определяется';

export function TeacherAnalytics({ summary, error, onRetry }: TeacherAnalyticsProps) {
  const maxDistribution = Math.max(1, ...(summary?.scoreDistribution.map((item) => item.count) ?? []));
  const maxErrors = Math.max(1, ...(summary?.topErrors.map((item) => item.count) ?? []));

  return (
    <section className="teacher-analytics" aria-labelledby="teacher-analytics-title">
      <Group justify="space-between" align="flex-start" gap="sm" wrap="nowrap">
        <div>
          <Title order={2} id="teacher-analytics-title">Аналитика обучения</Title>
          <Text size="sm" c="dimmed" mt={3}>Данные Core из сохранённых отчётов, без персональных данных.</Text>
        </div>
        {summary && summary.completedSessions > 0 && (
          <Badge size="lg" variant="light" color="blue">Занятий: {summary.completedSessions}</Badge>
        )}
      </Group>

      <Group className="analytics-scope" gap="xs" mt="sm">
        <Text size="xs"><strong>Выборка:</strong> оценённые карточные занятия</Text>
        <Text size="xs"><strong>Период UTC:</strong> {error ? 'недоступен' : getPeriod(summary)}</Text>
      </Group>

      {error ? (
        <Alert
          className="analytics-state"
          color="red"
          icon={<IconAlertCircle size={18} />}
          title="Аналитика не загрузилась"
        >
          <Group justify="space-between" gap="sm">
            <Text size="sm">{error}</Text>
            <Button color="red" variant="light" size="xs" onClick={onRetry}>Повторить</Button>
          </Group>
        </Alert>
      ) : summary === null ? (
        <Paper className="analytics-state" withBorder role="status">
          <Loader size="sm" aria-label="Загрузка аналитики" />
          <div>
            <Text fw={650}>Загружаем аналитику</Text>
            <Text size="xs" c="dimmed">Ожидаем сводку фактических отчётов от Core.</Text>
          </div>
        </Paper>
      ) : summary.completedSessions === 0 ? (
        <Paper className="analytics-state analytics-state--empty" withBorder role="status">
          <IconInbox size={24} aria-hidden="true" />
          <div>
            <Text fw={650}>Нет оценённых занятий</Text>
            <Text size="xs" c="dimmed">Графики появятся после первого сохранённого отчёта Core.</Text>
          </div>
        </Paper>
      ) : (
        <>
          <div className="analytics-kpis" aria-label="Сводные показатели">
            <div><Text size="xs" c="dimmed">Средний балл</Text><Text fw={750}>{formatPercent(summary.averagePercent)}</Text></div>
            <div><Text size="xs" c="dimmed">Медиана</Text><Text fw={750}>{formatPercent(summary.medianPercent)}</Text></div>
            <div><Text size="xs" c="dimmed">Типов происшествий</Text><Text fw={750}>{summary.incidentTypes.length}</Text></div>
          </div>

          <div className="analytics-grid">
            <Paper component="article" className="analytics-card" withBorder>
              <Group gap="xs" mb="sm"><IconChartHistogram size={18} aria-hidden="true" /><Title order={3}>Динамика оценок</Title></Group>
              {summary.daily.length === 0 ? (
                <Text size="sm" c="dimmed">За выбранный период нет точек.</Text>
              ) : (
                <div className="trend-chart" role="img" aria-label="Средний балл по дням">
                  {summary.daily.map((item) => (
                    <div className="trend-column" key={item.day} title={`${item.day}: ${formatPercent(item.averagePercent)}`}>
                      <Text size="xs" fw={700}>{formatPercent(item.averagePercent)}</Text>
                      <div className="trend-track">
                        <span style={{ height: `${Math.max(6, item.averagePercent)}%` }} />
                      </div>
                      <Text size="xs" c="dimmed">{formatDay(item.day)}</Text>
                      <Text size="xs" c="dimmed">{item.count} зан.</Text>
                    </div>
                  ))}
                </div>
              )}
            </Paper>

            <Paper component="article" className="analytics-card" withBorder>
              <Title order={3} mb="sm">Распределение результатов</Title>
              <Stack gap={7} role="list" aria-label="Количество занятий по диапазонам баллов">
                {summary.scoreDistribution.map((item) => (
                  <div className="distribution-row" role="listitem" key={item.label}>
                    <Text size="xs">{item.label}%</Text>
                    <div className="distribution-track"><span style={{ width: `${item.count / maxDistribution * 100}%` }} /></div>
                    <Text size="xs" fw={700}>{item.count}</Text>
                  </div>
                ))}
              </Stack>
            </Paper>

            <Paper component="article" className="analytics-card" withBorder>
              <Title order={3} mb="sm">Ошибки по критериям</Title>
              {summary.topErrors.length === 0 ? (
                <Text size="sm" c="dimmed">Ошибок по критериям не зафиксировано.</Text>
              ) : (
                <div className="error-heatmap" role="table" aria-label="Частота ошибок по критериям">
                  {summary.topErrors.map((item) => (
                    <div className="error-heatmap__row" role="row" key={item.criterionCode}>
                      <Text size="xs" ff="monospace" role="cell">{item.criterionCode}</Text>
                      <span
                        className="error-heatmap__cell"
                        role="cell"
                        aria-label={`${item.count} ошибок`}
                        style={{ '--heat': item.count / maxErrors } as CSSProperties}
                      />
                      <Text size="xs" fw={700} role="cell">{item.count}</Text>
                    </div>
                  ))}
                </div>
              )}
            </Paper>
          </div>
        </>
      )}
    </section>
  );
}
