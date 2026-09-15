import type { Icon } from '@tabler/icons-react';
import { IconBriefcase, IconSchool, IconUser } from '@tabler/icons-react';

export type Role = 'admin' | 'teacher' | 'student';

export const roles: Record<Role, {
  label: string;
  path: string;
  icon: Icon;
}> = {
  admin: {
    label: 'Администратор',
    path: '/admin',
    icon: IconBriefcase,
  },
  teacher: {
    label: 'Преподаватель',
    path: '/teacher',
    icon: IconSchool,
  },
  student: {
    label: 'Обучающийся',
    path: '/student',
    icon: IconUser,
  },
};
