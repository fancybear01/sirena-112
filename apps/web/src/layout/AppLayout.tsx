import { AppShell, Button, Group } from '@mantine/core';
import { Outlet, useLocation } from 'react-router';
import { useAuthSession } from '../auth/AuthSession';
import { Brand } from '../shared/Brand';

export function AppLayout() {
  const isStudentPage = useLocation().pathname === '/student';
  const auth = useAuthSession();
  return (
    <AppShell header={{ height: 68 }} padding="xl">
      <AppShell.Header className="shell-header">
        <Group h="100%" px="xl" justify="space-between" wrap="nowrap">
          <Brand />
          <Button variant="subtle" color="gray" size="sm" onClick={() => void auth.logout()}>Выйти</Button>
        </Group>
      </AppShell.Header>

      <AppShell.Main className="shell-main">
        <div className={`content-wrap${isStudentPage ? ' content-wrap--student' : ''}`}><Outlet /></div>
      </AppShell.Main>
    </AppShell>
  );
}
