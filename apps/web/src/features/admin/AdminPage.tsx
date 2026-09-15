import { useState } from 'react';
import { Group, SegmentedControl, Stack, Text, Title } from '@mantine/core';
import { IconActivity, IconBriefcase, IconSettings, IconUsers } from '@tabler/icons-react';
import { EmptyState, ErrorState, LoadingState } from '../../shared/StatePlaceholder';
import { WorkspaceScaffold } from '../../shared/WorkspaceScaffold';

type PreviewState = 'empty' | 'loading' | 'error';

export function AdminPage() {
  const [preview, setPreview] = useState<PreviewState>('empty');

  return (
    <Stack gap="xl">
      <WorkspaceScaffold
        eyebrow="РАЗДЕЛ АДМИНИСТРАТОРА"
        title="Платформа под контролем"
        description="Управляйте доступом и конфигурацией учебной среды. Раздел готов к дальнейшей разработке команды администраторов."
        icon={IconBriefcase}
        color="blue"
        modules={[
          { title: 'Пользователи', description: 'Учётные записи и распределение ролей.', icon: IconUsers },
          { title: 'Состояние системы', description: 'Компоненты платформы и их доступность.', icon: IconActivity },
          { title: 'Настройки', description: 'Конфигурация учебной среды.', icon: IconSettings },
        ]}
        emptyTitle="Пока нет пользователей"
        emptyDescription="Список пользователей появится после подключения Core API."
      />
      <section aria-labelledby="states-title">
        <Group justify="space-between" mb="md" align="flex-end">
          <div>
            <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={5}>ОБЩИЕ КОМПОНЕНТЫ</Text>
            <Title id="states-title" order={2}>Состояния интерфейса</Title>
          </div>
          <SegmentedControl
            aria-label="Выбрать состояние интерфейса"
            value={preview}
            onChange={(value) => setPreview(value as PreviewState)}
            data={[
              { label: 'Empty', value: 'empty' },
              { label: 'Loading', value: 'loading' },
              { label: 'Error', value: 'error' },
            ]}
          />
        </Group>
        {preview === 'loading' && <LoadingState />}
        {preview === 'error' && <ErrorState onRetry={() => setPreview('loading')} />}
        {preview === 'empty' && <EmptyState />}
      </section>
    </Stack>
  );
}
