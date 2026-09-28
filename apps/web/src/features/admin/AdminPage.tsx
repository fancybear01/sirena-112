import { useEffect, useState } from 'react';
import { Alert, Button, Group, Paper, PasswordInput, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import type { AuthRole } from '../../api/auth';
import { apiConfig } from '../../api/config';
import { createHttpClient } from '../../api/httpClient';

type GroupRecord = { id: string; name: string };
type UserRecord = { id: string; username: string; displayName: string; role: AuthRole;
  groupId: string | null; locked: boolean; enabled: boolean };
const http = createHttpClient(apiConfig.baseUrl);

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

  async function refresh() {
    const [groupList, userList] = await Promise.all([
      http.request<GroupRecord[]>('/api/admin/groups'), http.request<UserRecord[]>('/api/admin/users'),
    ]);
    setGroups(groupList);
    setUsers(userList);
    setGroupId((current) => current ?? groupList[0]?.id ?? null);
  }

  useEffect(() => { void refresh().catch(() => setError('Не удалось загрузить пользователей.')); }, []);

  async function run(action: () => Promise<unknown>) {
    setError('');
    try { await action(); await refresh(); }
    catch { setError('Операция не выполнена. Проверьте данные и права доступа.'); }
  }

  return <Stack gap="xl">
    <Title order={1}>Пользователи и группы</Title>
    {error && <Alert color="red" role="alert">{error}</Alert>}
    <Paper withBorder p="lg" radius="lg">
      <Text fw={600} mb="sm">Новая группа</Text>
      <Group align="end">
        <TextInput label="Название" value={groupName} onChange={(e) => setGroupName(e.currentTarget.value)} />
        <Button disabled={groupName.trim().length < 2} onClick={() => void run(async () => {
          await http.request('/api/admin/groups', { method: 'POST', body: { name: groupName } });
          setGroupName('');
        })}>Создать группу</Button>
      </Group>
    </Paper>
    <Paper withBorder p="lg" radius="lg">
      <Text fw={600} mb="sm">Новый пользователь</Text>
      <Group align="end">
        <TextInput label="Логин" value={username} onChange={(e) => setUsername(e.currentTarget.value)} />
        <TextInput label="Имя" value={displayName} onChange={(e) => setDisplayName(e.currentTarget.value)} />
        <PasswordInput label="Пароль (12+ символов)" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
        <Select label="Роль" data={['ADMIN', 'TEACHER', 'STUDENT']} value={role}
          onChange={(value) => setRole(value as AuthRole)} />
        {role !== 'ADMIN' && <Select label="Группа" data={groups.map((group) => ({ value: group.id, label: group.name }))}
          value={groupId} onChange={setGroupId} />}
        <Button disabled={!username || !displayName || password.length < 12 || (role !== 'ADMIN' && !groupId)}
          onClick={() => void run(async () => {
            await http.request('/api/admin/users', { method: 'POST', body: {
              username, password, displayName, role, groupId: role === 'ADMIN' ? null : groupId,
            } });
            setUsername(''); setPassword(''); setDisplayName('');
          })}>Создать</Button>
      </Group>
    </Paper>
    <Paper withBorder p="lg" radius="lg">
      <Text fw={600} mb="sm">Учётные записи</Text>
      <Table striped highlightOnHover>
        <Table.Thead><Table.Tr><Table.Th>Логин</Table.Th><Table.Th>Имя</Table.Th>
          <Table.Th>Роль</Table.Th><Table.Th>Группа</Table.Th><Table.Th>Доступ</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{users.map((user) => <Table.Tr key={user.id}>
          <Table.Td>{user.username}</Table.Td><Table.Td>{user.displayName}</Table.Td>
          <Table.Td><Select aria-label={`Роль ${user.username}`} data={['ADMIN', 'TEACHER', 'STUDENT']}
            value={user.role} onChange={(value) => { if (value) void run(() => http.request(`/api/admin/users/${user.id}/role`, {
              method: 'PATCH', body: { role: value, groupId: value === 'ADMIN' ? null : user.groupId ?? groups[0]?.id },
            })); }} /></Table.Td>
          <Table.Td>{user.role === 'ADMIN' ? '—' : <Select aria-label={`Группа ${user.username}`}
            data={groups.map((group) => ({ value: group.id, label: group.name }))} value={user.groupId}
            onChange={(value) => { if (value) void run(() => http.request(`/api/admin/users/${user.id}/role`, {
              method: 'PATCH', body: { role: user.role, groupId: value },
            })); }} />}</Table.Td>
          <Table.Td><Button size="xs" variant="light" color={user.locked ? 'teal' : 'red'}
            onClick={() => void run(() => http.request(`/api/admin/users/${user.id}/lock`, {
              method: 'PATCH', body: { locked: !user.locked },
            }))}>{user.locked ? 'Разблокировать' : 'Заблокировать'}</Button></Table.Td>
        </Table.Tr>)}</Table.Tbody>
      </Table>
    </Paper>
  </Stack>;
}
