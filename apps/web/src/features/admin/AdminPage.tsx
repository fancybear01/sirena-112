import { useEffect, useState } from 'react';
import { Alert, Button, Group, Paper, PasswordInput, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import type { AuthRole } from '../../api/auth';
import { apiConfig } from '../../api/config';
import { createHttpClient } from '../../api/httpClient';
import { AdminSystemPanel } from './AdminSystemPanel';

type GroupRecord = { id: string; name: string };
type UserRecord = { id: string; username: string; displayName: string; role: AuthRole;
  groupId: string | null; locked: boolean; enabled: boolean };
const http = createHttpClient(apiConfig.baseUrl);
const roleOptions = [
  { value: 'ADMIN', label: 'Администратор' },
  { value: 'TEACHER', label: 'Преподаватель' },
  { value: 'STUDENT', label: 'Обучающийся' },
];

export function AdminPage() {
  const [groups, setGroups] = useState<GroupRecord[]>([]);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [groupName, setGroupName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<AuthRole>('STUDENT');
  const [groupId, setGroupId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [groupList, userList] = await Promise.all([
      http.request<GroupRecord[]>('/api/admin/groups'), http.request<UserRecord[]>('/api/admin/users'),
    ]);
    setGroups(groupList);
    setUsers(userList);
    setGroupId((current) => current ?? groupList[0]?.id ?? null);
  }

  useEffect(() => {
    void refresh()
      .catch(() => setError('Не удалось загрузить пользователей и группы.'))
      .finally(() => setLoading(false));
  }, []);

  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await refresh(); }
    catch { setError('Операция не выполнена. Проверьте данные и права доступа.'); }
    finally { setBusy(false); }
  }

  return <Stack className="admin-page" gap="xl" aria-busy={loading || busy}>
    <AdminSystemPanel />
    <Title order={2}>Пользователи и группы</Title>
    {error && <Alert color="red" role="alert">{error}</Alert>}
    {loading && <Text role="status" aria-live="polite">Загружаем пользователей и группы…</Text>}
    <Paper component="form" withBorder p="lg" radius="lg" onSubmit={(event) => {
      event.preventDefault();
      if (groupName.trim().length < 2 || busy) return;
      void run(async () => {
        await http.request('/api/admin/groups', { method: 'POST', body: { name: groupName } });
        setGroupName('');
      });
    }}>
      <Text fw={600} mb="sm">Новая группа</Text>
      <Group className="responsive-form-row" align="end">
        <TextInput label="Название" value={groupName} onChange={(e) => setGroupName(e.currentTarget.value)} disabled={loading || busy} />
        <Button type="submit" loading={busy} disabled={loading || groupName.trim().length < 2}>Создать группу</Button>
      </Group>
    </Paper>
    <Paper component="form" withBorder p="lg" radius="lg" onSubmit={(event) => {
      event.preventDefault();
      if (!username || !displayName || password.length < 12 || (role !== 'ADMIN' && !groupId) || busy) return;
      void run(async () => {
        await http.request('/api/admin/users', { method: 'POST', body: {
          username, password, displayName, role, groupId: role === 'ADMIN' ? null : groupId,
        } });
        setUsername(''); setPassword(''); setDisplayName('');
      });
    }}>
      <Text fw={600} mb="sm">Новый пользователь</Text>
      <Group className="responsive-form-row" align="end">
        <TextInput label="Логин" autoComplete="username" value={username} onChange={(e) => setUsername(e.currentTarget.value)} disabled={loading || busy} />
        <TextInput label="Имя" autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.currentTarget.value)} disabled={loading || busy} />
        <PasswordInput label="Пароль (12+ символов)" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} disabled={loading || busy} />
        <Select label="Роль" data={roleOptions} value={role}
          onChange={(value) => setRole(value as AuthRole)} disabled={loading || busy} />
        {role !== 'ADMIN' && <Select label="Группа" data={groups.map((group) => ({ value: group.id, label: group.name }))}
          value={groupId} onChange={setGroupId} disabled={loading || busy} />}
        <Button type="submit" loading={busy}
          disabled={loading || !username || !displayName || password.length < 12 || (role !== 'ADMIN' && !groupId)}>Создать</Button>
      </Group>
    </Paper>
    <Paper withBorder p="lg" radius="lg">
      <Text fw={600} mb="sm">Учётные записи</Text>
      <Table className="admin-table" striped highlightOnHover>
        <Table.Thead><Table.Tr><Table.Th>Логин</Table.Th><Table.Th>Имя</Table.Th>
          <Table.Th>Роль</Table.Th><Table.Th>Группа</Table.Th><Table.Th>Доступ</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{users.map((user) => <Table.Tr key={user.id}>
          <Table.Td data-label="Логин">{user.username}</Table.Td><Table.Td data-label="Имя">{user.displayName}</Table.Td>
          <Table.Td data-label="Роль"><Select aria-label={`Роль ${user.username}`} data={roleOptions}
            disabled={busy}
            value={user.role} onChange={(value) => { if (value) void run(() => http.request(`/api/admin/users/${user.id}/role`, {
              method: 'PATCH', body: { role: value, groupId: value === 'ADMIN' ? null : user.groupId ?? groups[0]?.id },
            })); }} /></Table.Td>
          <Table.Td data-label="Группа">{user.role === 'ADMIN' ? '—' : <Select aria-label={`Группа ${user.username}`}
            disabled={busy}
            data={groups.map((group) => ({ value: group.id, label: group.name }))} value={user.groupId}
            onChange={(value) => { if (value) void run(() => http.request(`/api/admin/users/${user.id}/role`, {
              method: 'PATCH', body: { role: user.role, groupId: value },
            })); }} />}</Table.Td>
          <Table.Td data-label="Доступ"><Button size="xs" variant="light" color={user.locked ? 'teal' : 'red'}
            loading={busy}
            onClick={() => void run(() => http.request(`/api/admin/users/${user.id}/lock`, {
              method: 'PATCH', body: { locked: !user.locked },
            }))}>{user.locked ? 'Разблокировать' : 'Заблокировать'}</Button></Table.Td>
        </Table.Tr>)}</Table.Tbody>
      </Table>
    </Paper>
  </Stack>;
}
