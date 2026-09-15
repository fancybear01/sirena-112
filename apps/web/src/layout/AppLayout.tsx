import { AppShell, Avatar, Badge, Burger, Button, Divider, Group, NavLink, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconArrowRight, IconLayoutDashboard, IconLogout, IconShieldCheck } from '@tabler/icons-react';
import { Link, Outlet, useLocation } from 'react-router';
import { Brand } from '../shared/Brand';
import { getRememberedRole, roles, type Role } from '../shared/roles';

const roleOrder: Role[] = ['admin', 'teacher', 'student'];

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure(false);
  const { pathname } = useLocation();
  const activeRole = roleOrder.find((role) => pathname === roles[role].path);
  const displayRole = activeRole ?? getRememberedRole();

  return (
    <AppShell
      header={{ height: 76 }}
      navbar={{ width: 268, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="xl"
    >
      <AppShell.Header className="shell-header">
        <Group h="100%" px="xl" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Открыть навигацию" />
            <div className="shell-header__heading">
              <Text size="xs" c="dimmed" fw={600}>РАБОЧЕЕ ПРОСТРАНСТВО</Text>
              <Text fw={700} size="lg">{activeRole ? roles[activeRole].label : 'Сирена-112'}</Text>
            </div>
          </Group>
          <Group gap="md" wrap="nowrap">
            <Badge variant="light" color="teal" size="lg" className="shell-header__badge">Демо-режим</Badge>
            <Avatar color="blue" radius="xl" variant="light" aria-label="Демо-пользователь">
              {displayRole ? roles[displayRole].label[0] : 'С'}
            </Avatar>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="shell-navbar" p="lg">
        <AppShell.Section>
          <Brand />
          <Divider my="xl" />
          <Text size="xs" c="dimmed" fw={700} tt="uppercase" mb="sm" className="nav-caption">
            Разделы платформы
          </Text>
        </AppShell.Section>
        <AppShell.Section grow>
          <Stack gap={4}>
            {roleOrder.map((role) => {
              const Icon = roles[role].icon;
              return (
                <NavLink
                  key={role}
                  component={Link}
                  to={roles[role].path}
                  onClick={close}
                  active={activeRole === role}
                  label={roles[role].label}
                  leftSection={<Icon size={19} stroke={1.8} />}
                  rightSection={activeRole === role ? <IconArrowRight size={16} /> : undefined}
                  className="role-nav-link"
                />
              );
            })}
          </Stack>
        </AppShell.Section>
        <AppShell.Section>
          <div className="sidebar-note">
            <IconShieldCheck size={20} stroke={1.7} />
            <div>
              <Text fw={700} size="sm">Каркас интерфейса</Text>
              <Text size="xs" c="dimmed">Данные и вход пока демонстрационные.</Text>
            </div>
          </div>
          <Button
            component={Link}
            to="/login"
            onClick={close}
            variant="subtle"
            color="gray"
            fullWidth
            justify="flex-start"
            leftSection={<IconLogout size={18} />}
            mt="md"
          >
            Сменить роль
          </Button>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main className="shell-main">
        <div className="content-wrap">
          <div className="page-breadcrumb">
            <IconLayoutDashboard size={16} stroke={1.8} />
            <span>Сирена-112</span>
            <span className="page-breadcrumb__separator">/</span>
            <span>{activeRole ? roles[activeRole].label : 'Страница не найдена'}</span>
          </div>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  );
}
