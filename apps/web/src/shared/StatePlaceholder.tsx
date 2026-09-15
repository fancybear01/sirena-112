import { Button, Center, Loader, Paper, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import { IconAlertTriangle, IconInbox } from '@tabler/icons-react';

type BaseProps = {
  title?: string;
  description?: string;
};

export function LoadingState({
  title = 'Загружаем данные',
  description = 'Подождите немного — содержимое скоро появится.',
}: BaseProps) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg">
      <Center><Loader size="md" aria-label="Загрузка" /></Center>
      <Title order={3}>{title}</Title>
      <Text c="dimmed" size="sm">{description}</Text>
    </Paper>
  );
}

export function ErrorState({
  title = 'Не удалось загрузить данные',
  description = 'Попробуйте ещё раз позднее.',
  onRetry,
}: BaseProps & { onRetry?: () => void }) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg" role="alert">
      <Stack align="center" gap="sm">
        <ThemeIcon size={52} radius="xl" color="red" variant="light">
          <IconAlertTriangle size={26} stroke={1.8} />
        </ThemeIcon>
        <Title order={3}>{title}</Title>
        <Text c="dimmed" size="sm">{description}</Text>
        {onRetry && <Button variant="light" color="red" onClick={onRetry}>Повторить</Button>}
      </Stack>
    </Paper>
  );
}

export function EmptyState({
  title = 'Пока ничего нет',
  description = 'Новые данные появятся здесь.',
  actionLabel,
  onAction,
}: BaseProps & { actionLabel?: string; onAction?: () => void }) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg">
      <Stack align="center" gap="sm">
        <ThemeIcon size={52} radius="xl" color="blue" variant="light">
          <IconInbox size={27} stroke={1.7} />
        </ThemeIcon>
        <Title order={3}>{title}</Title>
        <Text c="dimmed" size="sm">{description}</Text>
        {actionLabel && onAction && <Button variant="light" onClick={onAction}>{actionLabel}</Button>}
      </Stack>
    </Paper>
  );
}
