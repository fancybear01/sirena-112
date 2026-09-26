import { Button, Group, Paper, PasswordInput, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { IconChevronRight } from '@tabler/icons-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { authApi, pathForRole, secureAuth } from '../api/auth';
import { Brand } from '../shared/Brand';
import { roles, type Role } from '../shared/roles';

const roleOrder: Role[] = ['admin', 'teacher', 'student'];

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const user = await authApi.login(username, password);
      navigate(pathForRole(user.role));
    } catch {
      setError('Не удалось войти. Проверьте логин и пароль.');
    } finally {
      setBusy(false);
    }
  }

  function enterAs(role: Role) {
    navigate(roles[role].path);
  }

  return (
    <main className="login-page">
      <Paper className="login-panel" radius="xl" withBorder shadow="sm">
        <Brand />
        {secureAuth ? (
          <>
            <Title order={1} mt="xl">Вход в систему</Title>
            <Text c="dimmed" size="sm" mt={6} mb="xl">Используйте свою учётную запись</Text>
            <form onSubmit={signIn}>
              <Stack gap="md">
                <TextInput label="Логин" value={username} onChange={(event) => setUsername(event.currentTarget.value)} required />
                <PasswordInput label="Пароль" value={password} onChange={(event) => setPassword(event.currentTarget.value)} required />
                {error && <Text c="red" role="alert">{error}</Text>}
                <Button type="submit" loading={busy}>Войти</Button>
              </Stack>
            </form>
          </>
        ) : (
          <>
        <Title order={1} mt="xl">Выберите роль</Title>
        <Text c="dimmed" size="sm" mt={6} mb="xl">Демо-вход без пароля</Text>

        <Stack gap="sm">
          {roleOrder.map((role) => {
            const { icon: Icon, label } = roles[role];
            return (
              <UnstyledButton
                key={role}
                className="login-role-card"
                onClick={() => enterAs(role)}
                aria-label={`Войти как ${label.toLowerCase()}`}
              >
                <Group gap="md" wrap="nowrap">
                  <span className="login-role-card__icon" aria-hidden="true">
                    <Icon size={21} stroke={1.8} />
                  </span>
                  <Text fw={600} size="md">{label}</Text>
                  <IconChevronRight size={18} stroke={1.8} className="login-role-card__arrow" aria-hidden="true" />
                </Group>
              </UnstyledButton>
            );
          })}
        </Stack>
          </>
        )}
      </Paper>
    </main>
  );
}
