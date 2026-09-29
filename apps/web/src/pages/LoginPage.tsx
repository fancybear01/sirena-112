import { Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { pathForRole } from '../api/auth';
import { useAuthSession } from '../auth/AuthSession';
import { Brand } from '../shared/Brand';

export function LoginPage() {
  const navigate = useNavigate();
  const auth = useAuthSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const user = await auth.login(username, password);
      navigate(pathForRole(user.role));
    } catch {
      setError('Не удалось войти. Проверьте логин и пароль.');
    } finally {
      setBusy(false);
    }
  }

  if (auth.status === 'authenticated') return <Navigate to={pathForRole(auth.user.role)} replace />;

  return (
    <main className="login-page">
      <Paper className="login-panel" radius="xl" withBorder shadow="sm">
        <Brand />
        <Title order={1} mt="xl">Вход в систему</Title>
        <Text c="dimmed" size="sm" mt={6} mb="xl">
          {auth.status === 'loading' ? 'Проверяем текущую сессию…' : 'Используйте свою учётную запись'}
        </Text>
        <form onSubmit={signIn} aria-busy={busy}>
          <Stack gap="md">
            <TextInput label="Логин" autoComplete="username" value={username}
              onChange={(event) => setUsername(event.currentTarget.value)} required disabled={auth.status === 'loading'} />
            <PasswordInput label="Пароль" autoComplete="current-password" value={password}
              onChange={(event) => setPassword(event.currentTarget.value)} required disabled={auth.status === 'loading'} />
            {error && <Text c="red" role="alert" aria-live="assertive">{error}</Text>}
            <Button type="submit" loading={busy} disabled={auth.status === 'loading'}>Войти</Button>
          </Stack>
        </form>
      </Paper>
    </main>
  );
}
