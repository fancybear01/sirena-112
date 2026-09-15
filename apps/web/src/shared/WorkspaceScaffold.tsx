import { Badge, Group, Paper, SimpleGrid, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import type { Icon } from '@tabler/icons-react';
import { EmptyState } from './StatePlaceholder';

export type WorkspaceModule = {
  title: string;
  description: string;
  icon: Icon;
};

type Props = {
  eyebrow: string;
  title: string;
  description: string;
  icon: Icon;
  color: string;
  modules: WorkspaceModule[];
  emptyTitle: string;
  emptyDescription: string;
};

export function WorkspaceScaffold({
  eyebrow, title, description, icon: HeroIcon, color, modules, emptyTitle, emptyDescription,
}: Props) {
  return (
    <Stack gap="xl">
      <Paper className="workspace-hero" withBorder radius="xl" p="xl">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Badge color={color} variant="light" size="lg" mb="lg">{eyebrow}</Badge>
            <Title order={1}>{title}</Title>
            <Text c="dimmed" mt="sm" maw={650}>{description}</Text>
          </div>
          <ThemeIcon className="workspace-hero__icon" color={color} variant="light" radius="xl" size={70}>
            <HeroIcon size={35} stroke={1.6} />
          </ThemeIcon>
        </Group>
      </Paper>

      <div>
        <Group justify="space-between" mb="md">
          <div>
            <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={5}>ОБЗОР РАЗДЕЛА</Text>
            <Title order={2}>Рабочие направления</Title>
          </div>
          <Badge color="gray" variant="light">3 модуля</Badge>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {modules.map(({ title: moduleTitle, description: moduleDescription, icon: Icon }, index) => (
            <Paper key={moduleTitle} withBorder radius="lg" p="lg" className="module-card">
              <Group justify="space-between" mb="xl">
                <ThemeIcon color={color} variant="light" size={43} radius="md">
                  <Icon size={22} stroke={1.8} />
                </ThemeIcon>
                <Text size="xs" c="dimmed" fw={700}>0{index + 1}</Text>
              </Group>
              <Title order={3}>{moduleTitle}</Title>
              <Text c="dimmed" size="sm" mt="xs">{moduleDescription}</Text>
            </Paper>
          ))}
        </SimpleGrid>
      </div>

      <div>
        <Group justify="space-between" mb="md">
          <div>
            <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={5}>СЕЙЧАС В РАЗДЕЛЕ</Text>
            <Title order={2}>Последние данные</Title>
          </div>
          <Badge color="blue" variant="outline">Mock-данные</Badge>
        </Group>
        <EmptyState title={emptyTitle} description={emptyDescription} />
      </div>
    </Stack>
  );
}
