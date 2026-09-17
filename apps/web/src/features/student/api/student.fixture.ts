import type { StudentScenario } from './types';

export const assignedScenarioFixture: StudentScenario = {
  id: '0c44dd40-9423-4e58-8905-fc7b45c26dd4',
  version: 1,
  title: 'Пожар в жилом доме',
  category: 'FIRE',
  difficulty: 'BASIC',
  profile: 'Житель сообщает о густом дыме на лестничной площадке по адресу: ул. Лесная, д. 14. На пятом этаже могут оставаться люди.',
  timeLimitSeconds: 600,
  groundTruth: {
    incidentType: 'FIRE',
    address: 'ул. Лесная, д. 14',
    requiredServices: ['FIRE', 'AMBULANCE'],
  },
  rubric: {
    criteria: [
      { code: 'INCIDENT_TYPE', description: 'Верно определить тип происшествия', weight: 0.25, critical: true },
      { code: 'ADDRESS', description: 'Зафиксировать полный адрес', weight: 0.2 },
      { code: 'DESCRIPTION', description: 'Зафиксировать обстоятельства и угрозы', weight: 0.2 },
      { code: 'SERVICES', description: 'Выбрать необходимые службы', weight: 0.25 },
      { code: 'COMPLETENESS', description: 'Заполнить обязательные поля', weight: 0.1 },
    ],
  },
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
