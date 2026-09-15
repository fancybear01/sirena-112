import type { Icon } from '@tabler/icons-react';
import { IconBriefcase, IconSchool, IconUser } from '@tabler/icons-react';

export type Role = 'admin' | 'teacher' | 'student';

export const roles: Record<Role, {
  label: string;
  title: string;
  description: string;
  path: string;
  icon: Icon;
}> = {
  admin: {
    label: 'Администратор',
    title: 'Управление платформой',
    description: 'Пользователи, роли и состояние системы',
    path: '/admin',
    icon: IconBriefcase,
  },
  teacher: {
    label: 'Преподаватель',
    title: 'Проведение занятий',
    description: 'Сценарии, назначения и результаты',
    path: '/teacher',
    icon: IconSchool,
  },
  student: {
    label: 'Обучающийся',
    title: 'Прохождение обучения',
    description: 'Задания, карточки и история',
    path: '/student',
    icon: IconUser,
  },
};

const storageKey = 'sirena-112:mock-role';

export function rememberRole(role: Role) {
  try {
    window.localStorage.setItem(storageKey, role);
  } catch {
    // Local storage is optional for the mock session.
  }
}

export function getRememberedRole(): Role | null {
  try {
    const value = window.localStorage.getItem(storageKey);
    return value === 'admin' || value === 'teacher' || value === 'student'
      ? value
      : null;
  } catch {
    return null;
  }
}
