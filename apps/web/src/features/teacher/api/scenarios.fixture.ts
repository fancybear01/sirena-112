import type { Scenario } from '../../../api/types';
import type { ScenarioStatus } from './types';

export const scenarioFixtures: Scenario[] = [
  {
    id: '0c44dd40-9423-4e58-8905-fc7b45c26dd4',
    version: 1,
    title: 'Пожар в жилом доме',
    category: 'FIRE',
    difficulty: 'BASIC',
    profile: 'Звонок жильца о задымлении на лестничной площадке пятиэтажного дома.',
    timeLimitSeconds: 600,
    groundTruth: {
      incidentType: 'FIRE',
      requiredServices: ['FIRE', 'AMBULANCE'],
    },
    rubric: {
      criteria: [
        { code: 'INCIDENT_TYPE', description: 'Верно определить тип происшествия', weight: 0.4, critical: true },
        { code: 'SERVICES', description: 'Выбрать необходимые службы', weight: 0.6 },
      ],
    },
  },
  {
    id: '82cb1ba1-a23b-480c-95cd-7257e2bb687a',
    version: 2,
    title: 'ДТП с пострадавшими',
    category: 'ACCIDENT',
    difficulty: 'INTERMEDIATE',
    profile: 'Столкновение двух автомобилей на перекрёстке, движение частично перекрыто.',
    timeLimitSeconds: 480,
    groundTruth: {
      incidentType: 'ROAD_ACCIDENT',
      requiredServices: ['POLICE', 'AMBULANCE'],
    },
    rubric: {
      criteria: [
        { code: 'INCIDENT_TYPE', description: 'Верно определить тип происшествия', weight: 0.4, critical: true },
        { code: 'SERVICES', description: 'Выбрать необходимые службы', weight: 0.6 },
      ],
    },
  },
  {
    id: '4a259192-58ef-465e-b584-2c27bfb51cad',
    version: 1,
    title: 'Запах газа в подъезде',
    category: 'GAS',
    difficulty: 'ADVANCED',
    profile: 'Несколько жильцов сообщают о резком запахе газа на первом этаже.',
    timeLimitSeconds: 420,
    groundTruth: {
      incidentType: 'GAS_LEAK',
      requiredServices: ['GAS', 'FIRE'],
    },
    rubric: {
      criteria: [
        { code: 'INCIDENT_TYPE', description: 'Верно определить тип происшествия', weight: 0.4, critical: true },
        { code: 'SERVICES', description: 'Выбрать необходимые службы', weight: 0.6 },
      ],
    },
  },
];

export const scenarioStatusFixtures: Record<string, ScenarioStatus> = {
  '0c44dd40-9423-4e58-8905-fc7b45c26dd4': 'READY',
  '82cb1ba1-a23b-480c-95cd-7257e2bb687a': 'READY',
  '4a259192-58ef-465e-b584-2c27bfb51cad': 'DRAFT',
};
