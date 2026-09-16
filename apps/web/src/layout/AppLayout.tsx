import { AppShell, Button, Group } from '@mantine/core';
import { Link, Outlet } from 'react-router';
import { Brand } from '../shared/Brand';

export function AppLayout() {
  return (
    <AppShell header={{ height: 68 }} padding="xl">
      <AppShell.Header className="shell-header">
        <Group h="100%" px="xl" justify="space-between" wrap="nowrap">
          <Brand />
          <Button component={Link} to="/login" variant="subtle" color="gray" size="sm">
            Сменить роль
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Main className="shell-main">
        <div className="content-wrap"><Outlet /></div>
      </AppShell.Main>
    </AppShell>
  );
}
