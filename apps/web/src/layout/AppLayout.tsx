import { AppShell, Burger, Button, Group, NavLink, Stack } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Link, Outlet, useLocation } from 'react-router';
import { Brand } from '../shared/Brand';
import { roles, type Role } from '../shared/roles';

const roleOrder: Role[] = ['admin', 'teacher', 'student'];

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure(false);
  const { pathname } = useLocation();

  return (
    <AppShell
      header={{ height: 68 }}
      navbar={{ width: 228, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="xl"
    >
      <AppShell.Header className="shell-header">
        <Group h="100%" px="xl" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Открыть навигацию" />
            <Brand />
          </Group>
          <Button component={Link} to="/login" onClick={close} variant="subtle" color="gray" size="sm">
            Сменить роль
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="shell-navbar" p="md">
        <Stack gap={4}>
          {roleOrder.map((role) => {
            const Icon = roles[role].icon;
            return (
              <NavLink
                key={role}
                component={Link}
                to={roles[role].path}
                onClick={close}
                active={pathname === roles[role].path}
                label={roles[role].label}
                leftSection={<Icon size={19} stroke={1.8} />}
                className="role-nav-link"
              />
            );
          })}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main className="shell-main">
        <div className="content-wrap"><Outlet /></div>
      </AppShell.Main>
    </AppShell>
  );
}
