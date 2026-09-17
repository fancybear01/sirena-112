import type { StudentScenario } from './types';

export const assignedScenarioFixture: StudentScenario = {
  id: '0c44dd40-9423-4e58-8905-fc7b45c26dd4',
  version: 1,
  title: 'Пожар в жилом доме',
  category: 'Пожар',
  difficulty: 'BASIC',
  profile: 'Житель сообщает о густом дыме на лестничной площадке по адресу: ул. Лесная, д. 14. На пятом этаже могут оставаться люди.',
  timeLimitSeconds: 600,
};

export const incidentTypeOptions = [
  { value: 'FIRE', label: 'Пожар' },
  { value: 'SMOKE', label: 'Задымление' },
  { value: 'GAS_LEAK', label: 'Утечка газа' },
  { value: 'ROAD_ACCIDENT', label: 'Дорожное происшествие' },
  { value: 'OTHER', label: 'Другое' },
];

export const serviceOptions = [
  { value: 'FIRE', label: 'Пожарная охрана' },
  { value: 'AMBULANCE', label: 'Скорая помощь' },
  { value: 'POLICE', label: 'Полиция' },
  { value: 'GAS', label: 'Аварийная газовая служба' },
];
