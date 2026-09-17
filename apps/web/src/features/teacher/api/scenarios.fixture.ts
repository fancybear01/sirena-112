import type { TeacherScenario } from './types';

export const scenarioFixtures: TeacherScenario[] = [
  {
    id: '0c44dd40-9423-4e58-8905-fc7b45c26dd4',
    version: 1,
    title: 'Пожар в жилом доме',
    category: 'Пожар',
    difficulty: 'BASIC',
    status: 'READY',
    profile: 'Звонок жильца о задымлении на лестничной площадке пятиэтажного дома.',
    timeLimitSeconds: 600,
    groundTruth: {
      incidentType: 'FIRE',
      requiredServices: ['FIRE', 'AMBULANCE'],
    },
    rubric: { passingScore: 70 },
  },
  {
    id: '82cb1ba1-a23b-480c-95cd-7257e2bb687a',
    version: 2,
    title: 'ДТП с пострадавшими',
    category: 'Дорожное происшествие',
    difficulty: 'INTERMEDIATE',
    status: 'READY',
    profile: 'Столкновение двух автомобилей на перекрёстке, движение частично перекрыто.',
    timeLimitSeconds: 480,
    groundTruth: {
      incidentType: 'ROAD_ACCIDENT',
      requiredServices: ['POLICE', 'AMBULANCE'],
    },
    rubric: { passingScore: 75 },
  },
  {
    id: '4a259192-58ef-465e-b584-2c27bfb51cad',
    version: 1,
    title: 'Запах газа в подъезде',
    category: 'Коммунальная авария',
    difficulty: 'ADVANCED',
    status: 'DRAFT',
    profile: 'Несколько жильцов сообщают о резком запахе газа на первом этаже.',
    timeLimitSeconds: 420,
    groundTruth: {
      incidentType: 'GAS_LEAK',
      requiredServices: ['GAS', 'FIRE'],
    },
    rubric: { passingScore: 80 },
  },
];
