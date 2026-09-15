import { IconClipboardList, IconHistory, IconNotes, IconUser } from '@tabler/icons-react';
import { WorkspaceScaffold } from '../../shared/WorkspaceScaffold';

export function StudentPage() {
  return (
    <WorkspaceScaffold
      eyebrow="РАЗДЕЛ ОБУЧАЮЩЕГОСЯ"
      title="Практика начинается здесь"
      description="Получайте задания, заполняйте карточки происшествий и возвращайтесь к своим результатам. Раздел можно развивать независимо от остальных интерфейсов."
      icon={IconUser}
      color="orange"
      modules={[
        { title: 'Мои задания', description: 'Текущие и предстоящие тренировки.', icon: IconClipboardList },
        { title: 'Карточка вызова', description: 'Работа с учебным происшествием.', icon: IconNotes },
        { title: 'История', description: 'Пройденные занятия и обратная связь.', icon: IconHistory },
      ]}
      emptyTitle="Заданий пока нет"
      emptyDescription="Преподаватель назначит занятие — оно появится в этом разделе."
    />
  );
}
