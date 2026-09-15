import { Button, Paper, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import { IconRouteOff } from '@tabler/icons-react';
import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <Paper className="not-found" withBorder radius="xl">
      <Stack align="center" gap="md">
        <ThemeIcon size={76} radius="xl" color="blue" variant="light">
          <IconRouteOff size={38} stroke={1.7} />
        </ThemeIcon>
        <Text className="not-found__code">404</Text>
        <Title order={1}>Страница не найдена</Title>
        <Text c="dimmed">Проверьте адрес или вернитесь к выбору роли.</Text>
        <Button component={Link} to="/login" mt="sm">К выбору роли</Button>
      </Stack>
    </Paper>
  );
}
