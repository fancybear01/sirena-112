import { IconBook2, IconCalendarEvent, IconChartBar, IconSchool } from '@tabler/icons-react';
import { WorkspaceScaffold } from '../../shared/WorkspaceScaffold';

export function TeacherPage() {
  return (
    <WorkspaceScaffold
      eyebrow="РАЗДЕЛ ПРЕПОДАВАТЕЛЯ"
      title="Обучение в ваших руках"
      description="Подготовьте сценарий, назначьте занятие и следите за результатами обучающихся. Для этого раздела выделено отдельное пространство разработки."
      icon={IconSchool}
      color="teal"
      modules={[
        { title: 'Сценарии', description: 'Библиотека и подготовка учебных ситуаций.', icon: IconBook2 },
        { title: 'Занятия', description: 'Назначения и запуск тренировок.', icon: IconCalendarEvent },
        { title: 'Отчёты', description: 'Результаты и журнал действий.', icon: IconChartBar },
      ]}
      emptyTitle="Занятий пока нет"
      emptyDescription="Назначенные занятия появятся здесь после подключения данных."
    />
  );
}
