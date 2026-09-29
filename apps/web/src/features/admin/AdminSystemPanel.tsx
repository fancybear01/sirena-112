import { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, Modal, Paper, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import {
  adminSystemApi,
  type AdminAction,
  type AuditEntry,
  type ManagedService,
  type SafeConfiguration,
  type SystemStatus,
} from './api/adminSystemApi';

const actionLabels: Record<AdminAction, string> = {
  start: 'Запустить', stop: 'Остановить', restart: 'Перезапустить', update: 'Обновить комплекс',
};
const sectionLabels: Record<keyof SafeConfiguration['sections'], string> = {
  sip: 'SIP и RTP', database: 'База данных', limits: 'Лимиты', logging: 'Журналирование',
};

function dateTime(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value));
}

function bytes(value?: number): string {
  if (!value) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let current = value;
  let unit = 0;
  while (current >= 1024 && unit < units.length - 1) { current /= 1024; unit += 1; }
  return `${current.toFixed(unit < 2 ? 0 : 1)} ${units[unit]}`;
}

export function AdminSystemPanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [configuration, setConfiguration] = useState<SafeConfiguration | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ action: AdminAction; service: ManagedService; label: string } | null>(null);

  const refresh = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const [nextStatus, nextConfiguration, nextAudit] = await Promise.all([
        adminSystemApi.status(), adminSystemApi.configuration(), adminSystemApi.audit(),
      ]);
      setStatus(nextStatus); setConfiguration(nextConfiguration); setAudit(nextAudit); setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Admin helper недоступен.');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function confirmAction() {
    if (!pending) return;
    setBusy(true); setError('');
    try {
      await adminSystemApi.action(pending.action, pending.service);
      setPending(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Управляющая команда не выполнена.');
    } finally {
      setBusy(false);
    }
  }

  return <Stack gap="lg">
    <Group justify="space-between" align="end">
      <div>
        <Title order={1}>Контроль локального комплекса</Title>
        <Text c="dimmed">Health, ресурсы, безопасные команды и параметры без раскрытия секретов.</Text>
      </div>
      <Button variant="light" loading={loading} onClick={() => void refresh(true)}>Обновить состояние</Button>
    </Group>

    {error && <Alert color="red" title="Админка не может получить данные" role="alert">
      {error} Запустите <code>python scripts/admin_helper.py</code> на сервере и проверьте вход с ролью администратора.
      Карточный режим от helper не зависит.
    </Alert>}

    {status && <>
      <Paper withBorder p="lg" radius="lg">
        <Group justify="space-between" mb="md">
          <Text fw={700}>Компоненты</Text>
          <Group gap="xs"><Badge color={status.status === 'UP' ? 'teal' : 'red'}>
            {status.status === 'UP' ? 'Комплекс готов' : 'Есть сбой'}
          </Badge><Text size="sm" c="dimmed">Обновлено {dateTime(status.updatedAt)}</Text></Group>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {status.services.map((service) => <Paper className="admin-service-card" withBorder p="md" key={service.id}>
            <Group justify="space-between"><Text fw={700}>{service.label}</Text>
              <Badge color={service.status === 'UP' ? 'teal' : 'red'}>{service.status === 'UP' ? 'Работает' : 'Сбой'}</Badge>
            </Group>
            <Text size="sm" c={service.status === 'UP' ? 'dimmed' : 'red'} mt="xs">{service.detail}</Text>
            <Group gap="xs" mt="md">
              {(['start', 'stop', 'restart'] as const).map((action) => <Button key={action} size="xs" variant="light"
                color={action === 'stop' ? 'red' : undefined} disabled={busy}
                aria-label={`${actionLabels[action]} ${service.label}`}
                onClick={() => setPending({ action, service: service.id, label: service.label })}>
                {actionLabels[action]}
              </Button>)}
            </Group>
          </Paper>)}
        </SimpleGrid>
      </Paper>

      <Paper withBorder p="lg" radius="lg">
        <Group justify="space-between" mb="md"><Text fw={700}>Ресурсы сервера</Text>
          <Group gap="xs">
            {(['start', 'stop', 'restart'] as const).map((action) => <Button key={action} size="xs" variant="light"
              color={action === 'stop' ? 'red' : undefined} disabled={busy}
              onClick={() => setPending({ action, service: 'all', label: 'весь комплекс' })}>
              {actionLabels[action]} всё
            </Button>)}
            <Button size="xs" color="orange" variant="light" disabled={busy}
              onClick={() => setPending({ action: 'update', service: 'all', label: 'весь комплекс' })}>
              Пакетное обновление
            </Button>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 3 }}>{status.resources.map((resource) => <div key={resource.id}>
          <Group justify="space-between"><Text>{resource.label}</Text><Text fw={700}>{resource.usedPercent.toFixed(1)}%</Text></Group>
          <Progress value={resource.usedPercent} color={resource.usedPercent >= 90 ? 'red' : resource.usedPercent >= 75 ? 'orange' : 'blue'} mt="xs" />
          {resource.totalBytes !== undefined && <Text size="xs" c="dimmed" mt={4}>{bytes(resource.usedBytes)} из {bytes(resource.totalBytes)}</Text>}
        </div>)}</SimpleGrid>
      </Paper>

      {status.errors.length > 0 && <Alert color="red" title="Значимые ошибки">
        <Stack gap={4}>{status.errors.map((item, index) => <Text size="sm" key={`${item.component}-${index}`}>
          <b>{item.component}:</b> {item.message}
        </Text>)}</Stack>
      </Alert>}
    </>}

    {configuration && <Paper withBorder p="lg" radius="lg">
      <Text fw={700}>Безопасная конфигурация</Text>
      <Text size="sm" c="dimmed" mb="md">Значения показаны только для разрешённых полей. Секреты не передаются в браузер и здесь не изменяются.</Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {(Object.keys(sectionLabels) as (keyof SafeConfiguration['sections'])[]).map((section) => <div key={section}>
          <Text fw={600} mb="xs">{sectionLabels[section]}</Text>
          {configuration.sections[section].map((field) => <Group justify="space-between" key={field.key} wrap="nowrap">
            <Text size="sm">{field.label}</Text><Text size="sm" ff="monospace">{field.value}</Text>
          </Group>)}
        </div>)}
      </SimpleGrid>
      <Alert color="blue" mt="md" title="Backup и восстановление">
        <ol className="admin-instructions">{configuration.backup.map((item) => <li key={item}>{item}</li>)}</ol>
      </Alert>
    </Paper>}

    <Paper className="admin-audit" withBorder p="lg" radius="lg">
      <Text fw={700} mb="sm">Аудит управляющих команд</Text>
      {audit.length === 0 ? <Text c="dimmed">Команды ещё не выполнялись.</Text> : <Table striped>
        <Table.Thead><Table.Tr><Table.Th>Время</Table.Th><Table.Th>Администратор</Table.Th>
          <Table.Th>Действие</Table.Th><Table.Th>Компонент</Table.Th><Table.Th>Результат</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{audit.filter((item) => item.outcome !== 'STARTED').map((item) => <Table.Tr key={`${item.id}-${item.timestamp}`}>
          <Table.Td>{dateTime(item.timestamp)}</Table.Td><Table.Td>{item.actor}</Table.Td>
          <Table.Td>{actionLabels[item.action]}</Table.Td><Table.Td>{item.service}</Table.Td>
          <Table.Td><Badge color={item.outcome === 'OK' ? 'teal' : 'red'}>{item.outcome}</Badge></Table.Td>
        </Table.Tr>)}</Table.Tbody>
      </Table>}
    </Paper>

    <Modal opened={pending !== null} onClose={() => { if (!busy) setPending(null); }} title="Подтверждение управляющей команды" centered>
      {pending && <Stack>
        <Alert color={pending.action === 'stop' ? 'red' : 'orange'}>
          {actionLabels[pending.action]}: {pending.label}. Команда ограничена allowlist и будет записана в аудит.
        </Alert>
        <Group justify="end"><Button variant="default" disabled={busy} onClick={() => setPending(null)}>Отмена</Button>
          <Button color={pending.action === 'stop' ? 'red' : 'blue'} loading={busy} onClick={() => void confirmAction()}>Подтвердить</Button>
        </Group>
      </Stack>}
    </Modal>
  </Stack>;
}
