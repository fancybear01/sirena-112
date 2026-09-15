import { Button, Loader, Paper, Text, ThemeIcon, Title } from '@mantine/core';
import { IconAlertTriangle, IconInbox } from '@tabler/icons-react';

type BaseProps = {
  title?: string;
  description?: string;
};

export function LoadingState({ title = 'Загрузка', description }: BaseProps) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg" role="status">
      <Loader size="sm" aria-label="Загрузка" />
      <Title order={3}>{title}</Title>
      {description && <Text c="dimmed" size="sm">{description}</Text>}
    </Paper>
  );
}

export function ErrorState({
  title = 'Не удалось загрузить данные',
  description,
  onRetry,
}: BaseProps & { onRetry?: () => void }) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg" role="alert">
      <ThemeIcon size={48} radius="xl" color="red" variant="light">
        <IconAlertTriangle size={24} stroke={1.8} />
      </ThemeIcon>
      <Title order={3}>{title}</Title>
      {description && <Text c="dimmed" size="sm">{description}</Text>}
      {onRetry && <Button variant="light" color="red" onClick={onRetry}>Повторить</Button>}
    </Paper>
  );
}

export function EmptyState({
  title = 'Пока пусто',
  description,
  actionLabel,
  onAction,
}: BaseProps & { actionLabel?: string; onAction?: () => void }) {
  return (
    <Paper className="state-placeholder" withBorder radius="lg">
      <ThemeIcon size={48} radius="xl" color="blue" variant="light">
        <IconInbox size={24} stroke={1.7} />
      </ThemeIcon>
      <Title order={3}>{title}</Title>
      {description && <Text c="dimmed" size="sm">{description}</Text>}
      {actionLabel && onAction && <Button variant="light" onClick={onAction}>{actionLabel}</Button>}
    </Paper>
  );
}
