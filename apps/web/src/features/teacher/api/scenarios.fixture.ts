import type { Scenario } from '../../../api/types';
import type { ScenarioStatus } from './types';

export const scenarioFixtures: Scenario[] = [
  {
    id: '80c14c89-f2b7-527a-bd6f-268cdc3d4a11',
    version: 3,
    title: 'Задымление в мусоропроводе',
    category: 'FIRE',
    difficulty: 'BASIC',
    profile: 'Житель сообщает о дыме из мусоропровода в жилом доме. Эталон классификатора: 1050602.',
    timeLimitSeconds: 30,
    groundTruth: {
      classifierVersion: '046-2024-11-15',
      classifierCode: '1050602',
      incidentType: 'задымление: мусоропровод',
      requiredServices: [{
        id: 'MCHS',
        displayName: 'Служба 101 (МЧС)',
        reasons: [{ ruleId: 'classifier.1050602.O', message: 'Маршрутизация по классификатору.', matchedInputIds: [] }],
      }],
    },
    rubric: {
      criteria: [
        { code: 'SIGNS', description: 'Выбрать признаки из каталога', weight: 0.5, critical: true },
        { code: 'ANSWERS', description: 'Ответить на дополнительные вопросы', weight: 0.5 },
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
  '80c14c89-f2b7-527a-bd6f-268cdc3d4a11': 'READY',
  '82cb1ba1-a23b-480c-95cd-7257e2bb687a': 'READY',
  '4a259192-58ef-465e-b584-2c27bfb51cad': 'DRAFT',
};
