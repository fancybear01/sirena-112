import { Group, Paper, Stack, Text, Title, UnstyledButton } from '@mantine/core';
import { IconChevronRight } from '@tabler/icons-react';
import { useNavigate } from 'react-router';
import { Brand } from '../shared/Brand';
import { roles, type Role } from '../shared/roles';

const roleOrder: Role[] = ['admin', 'teacher', 'student'];

export function LoginPage() {
  const navigate = useNavigate();

  function enterAs(role: Role) {
    navigate(roles[role].path);
  }

  return (
    <main className="login-page">
      <Paper className="login-panel" radius="xl" withBorder shadow="sm">
        <Brand />
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
      </Paper>
    </main>
  );
}
