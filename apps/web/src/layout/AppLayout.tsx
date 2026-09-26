import { AppShell, Button, Group } from '@mantine/core';
import { Link, Outlet, useLocation, useNavigate } from 'react-router';
import { authApi, secureAuth } from '../api/auth';
import { Brand } from '../shared/Brand';

export function AppLayout() {
  const isStudentPage = useLocation().pathname === '/student';
  const navigate = useNavigate();
  return (
    <AppShell header={{ height: 68 }} padding="xl">
      <AppShell.Header className="shell-header">
        <Group h="100%" px="xl" justify="space-between" wrap="nowrap">
          <Brand />
          {secureAuth ? <Button variant="subtle" color="gray" size="sm"
            onClick={() => { void authApi.logout().finally(() => navigate('/login')); }}>Выйти</Button>
            : <Button component={Link} to="/login" variant="subtle" color="gray" size="sm">Сменить роль</Button>}
        </Group>
      </AppShell.Header>

      <AppShell.Main className="shell-main">
        <div className={`content-wrap${isStudentPage ? ' content-wrap--student' : ''}`}><Outlet /></div>
      </AppShell.Main>
    </AppShell>
  );
}
