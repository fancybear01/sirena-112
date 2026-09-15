import { Button, Paper, Stack, ThemeIcon, Title } from '@mantine/core';
import { IconRouteOff } from '@tabler/icons-react';
import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <Paper className="not-found" withBorder radius="xl">
      <Stack align="center" gap="md">
        <ThemeIcon size={56} radius="xl" color="blue" variant="light">
          <IconRouteOff size={27} stroke={1.7} />
        </ThemeIcon>
        <Title order={1}>Страница не найдена</Title>
        <Button component={Link} to="/login" variant="light">К выбору роли</Button>
      </Stack>
    </Paper>
  );
}
