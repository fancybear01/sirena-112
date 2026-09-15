import { Stack, Title } from '@mantine/core';
import { EmptyState } from './StatePlaceholder';

export function WorkspacePage({ title }: { title: string }) {
  return (
    <Stack className="workspace-page" gap="xl">
      <Title order={1}>{title}</Title>
      <EmptyState />
    </Stack>
  );
}
