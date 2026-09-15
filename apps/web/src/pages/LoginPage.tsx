import { Badge, Box, Button, Group, Paper, Stack, Text, ThemeIcon, Title, UnstyledButton } from '@mantine/core';
import { IconArrowRight, IconCheck, IconLockOpen2, IconSparkles } from '@tabler/icons-react';
import { useNavigate } from 'react-router';
import { Brand } from '../shared/Brand';
import { rememberRole, roles, type Role } from '../shared/roles';

const roleOrder: Role[] = ['admin', 'teacher', 'student'];

export function LoginPage() {
  const navigate = useNavigate();

  function enterAs(role: Role) {
    rememberRole(role);
    navigate(roles[role].path);
  }

  return (
    <div className="login-page">
      <aside className="login-story">
        <Brand inverse />
        <div className="login-story__main">
          <Badge color="cyan" variant="light" size="lg" leftSection={<IconSparkles size={15} />}>
            Учебный симулятор 112
          </Badge>
          <Title order={1}>Тренировка решений, которые имеют значение.</Title>
          <Text>
            Одно пространство для управления обучением, проведения занятий и практики операторов.
          </Text>
          <Stack gap="md" mt="xl">
            {['Три независимых рабочих раздела', 'Единая навигация и компоненты', 'Готово к подключению данных'].map((item) => (
              <Group gap="sm" key={item} wrap="nowrap">
                <ThemeIcon radius="xl" color="cyan" variant="light" size={28}>
                  <IconCheck size={16} stroke={2} />
                </ThemeIcon>
                <Text size="sm">{item}</Text>
              </Group>
            ))}
          </Stack>
        </div>
        <Text className="login-story__footer" size="xs">СИРЕНА-112 · ДЕМО-ВЕРСИЯ</Text>
      </aside>

      <main className="login-content">
        <div className="login-content__inner">
          <Group justify="space-between" mb="xl">
            <Badge variant="light" color="blue" size="lg">Вход в платформу</Badge>
            <Text size="sm" c="dimmed">Демо-доступ</Text>
          </Group>
          <Title order={1}>Выберите свою роль</Title>
          <Text c="dimmed" mt="sm" mb="xl">
            Откройте нужный раздел без учётной записи. Позже здесь появится настоящий вход.
          </Text>

          <Stack gap="md">
            {roleOrder.map((role) => {
              const { icon: Icon, label, description } = roles[role];
              return (
                <UnstyledButton
                  key={role}
                  className={`login-role-card login-role-card--${role}`}
                  onClick={() => enterAs(role)}
                  aria-label={`Войти как ${label.toLowerCase()}`}
                >
                  <Paper withBorder radius="lg" p="lg" className="login-role-card__paper">
                    <Group justify="space-between" wrap="nowrap">
                      <Group gap="md" wrap="nowrap">
                        <Box className="login-role-card__icon"><Icon size={23} stroke={1.8} /></Box>
                        <div>
                          <Text fw={700} size="md">{label}</Text>
                          <Text c="dimmed" size="sm">{description}</Text>
                        </div>
                      </Group>
                      <IconArrowRight size={20} stroke={1.8} className="login-role-card__arrow" />
                    </Group>
                  </Paper>
                </UnstyledButton>
              );
            })}
          </Stack>

          <Paper className="login-hint" radius="lg" p="md" mt="xl">
            <Group gap="sm" wrap="nowrap">
              <IconLockOpen2 size={20} stroke={1.8} />
              <Text size="sm">Это mock-вход: выбор роли только открывает соответствующий маршрут.</Text>
            </Group>
          </Paper>
          <Button variant="subtle" color="gray" size="xs" mt="lg" disabled>
            Авторизация появится позже
          </Button>
        </div>
      </main>
    </div>
  );
}
