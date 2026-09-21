import type {
  CardFormDefinition,
  OperatorCardInput,
  QuestionDefinition,
  RoutedService,
} from '../../../api/types';
import type { StudentScenario } from './types';

export const referenceSignPath = [
  'sign.68eaae1dc9472ce9',
  'sign.8795ab4a7bb0d66a',
  'sign.8b0cf230ebb8ba99',
] as const;

const yesNoOptions = [
  { id: 'YES', label: 'Да' },
  { id: 'NO', label: 'Нет' },
];

export const referenceQuestions: QuestionDefinition[] = [
  { id: 'routing.culture-listed-facility', label: 'Объект из перечня', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.evacuation', label: 'Требуется эвакуация', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.medical-help', label: 'Медицинская помощь', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.no-access', label: 'Нет доступа', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.offence', label: 'Правонарушение', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.threat-to-people', label: 'Угроза людям', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  { id: 'routing.traffic-blocked', label: 'Перекрытие движения', inputType: 'SINGLE_SELECT', required: false, options: yesNoOptions },
  {
    id: 'routing.victims-status',
    label: 'Пострадавшие / погибшие',
    inputType: 'SINGLE_SELECT',
    required: false,
    options: [
      { id: 'NONE', label: 'Признак не выбран' },
      { id: 'PRESENT', label: 'Пострадавшие' },
      { id: 'NOT_ON_SCENE', label: 'Пострадавшие не на месте' },
    ],
  },
];

const serviceNames: Array<[string, string]> = [
  ['DGP_ARM112', 'ДГП — АРМ-112'],
  ['DGP_INTEGRATION', 'ДГП — интеграция'],
  ['FSO', 'ФСО'],
  ['GKH', 'Гор. Хозяйство'],
  ['MAYOR', 'Аппарат МЭРА'],
  ['MCHS', 'Служба 101 (МЧС)'],
  ['MOSBEZ', 'Департамент РБиПК (ГКУ МОСБЕЗ)'],
  ['MOSBEZ_ANALYTICS', 'МОСБЕЗ — МКП, Аналитика'],
  ['MOSOBLGAZ', 'Классификатор Мособлгаз'],
  ['MOSZHILINSPECTION', 'Мосжилинспекция'],
  ['NTU', 'ГКУ НТУ'],
  ['TERRITORIAL_OIV', 'Территориальные ОИВ'],
  ['TINAO', 'Территориальные ОИВ ТиНАО'],
  ['ZODD', 'ЦОДД'],
];

export const referenceRoutedServices: RoutedService[] = serviceNames.map(([id, displayName]) => ({
  id,
  displayName,
  reasons: [{
    ruleId: `classifier.1050602.${id}`,
    message: id === 'MCHS'
      ? 'Пожарная служба определяется типом происшествия и ответом о доступе.'
      : 'Маршрутизация рассчитана по записи классификатора 1050602.',
    matchedInputIds: id === 'MCHS' ? ['routing.no-access'] : [],
  }],
}));

export const referenceExpectedInput: OperatorCardInput = {
  caller: null,
  incident: {
    selectedSignIds: [...referenceSignPath],
    answers: referenceQuestions.map((question) => ({
      questionId: question.id,
      optionIds: [question.id === 'routing.victims-status' ? 'NONE' : 'NO'],
    })),
  },
  address: { displayAddress: 'Учебный адрес, дом 1' },
  description: 'Учебный пример: задымление: мусоропровод',
  victims: { present: false },
  facts: {},
};

export const assignedScenarioFixture: StudentScenario = {
  id: '80c14c89-f2b7-527a-bd6f-268cdc3d4a11',
  version: 3,
  title: 'Задымление в мусоропроводе',
  category: 'FIRE',
  difficulty: 'BASIC',
  profile: 'Житель сообщает о дыме из мусоропровода в жилом доме. Нужно уточнить признаки, адрес и обстоятельства, не подменяя выводы Core.',
  timeLimitSeconds: 30,
  groundTruth: {
    classifierVersion: '046-2024-11-15',
    classifierCode: '1050602',
    incidentType: 'задымление: мусоропровод',
    ekp35IncidentType: 'пожар: мусоропровод',
    responseScenarioCode: '1_9',
    responseScenarioStatus: 'CODE',
    mainServices: [{ id: 'MCHS', displayName: 'Служба 101 (МЧС)' }],
    requiredServices: referenceRoutedServices,
    expectedInput: referenceExpectedInput,
  },
  rubric: {
    criteria: [
      { code: 'SIGNS', description: 'Выбраны признаки из каталога', weight: 0.25, critical: true },
      { code: 'ANSWERS', description: 'Даны ответы на вопросы маршрутизации', weight: 0.25 },
      { code: 'SERVICES', description: 'Службы рассчитаны по каталогу', weight: 0.25 },
      { code: 'ADDRESS', description: 'Зафиксирован адрес', weight: 0.25 },
    ],
  },
};

export function createReferenceCardForm(selectedSignIds: string[] = []): CardFormDefinition {
  const hasLevel1 = selectedSignIds[0] === referenceSignPath[0];
  const hasLevel2 = hasLevel1 && selectedSignIds[1] === referenceSignPath[1];
  return {
    classifierVersion: '046-2024-11-15',
    signGroups: [
      {
        id: 'signs.level1',
        label: 'Группа происшествия',
        level: 1,
        required: true,
        options: [
          { id: referenceSignPath[0], label: 'Жилой дом' },
          { id: 'sign.04cd34ecea5dc65c', label: 'Автомашина' },
          { id: 'sign.01adff782665175e', label: 'Прорыв воды' },
        ],
      },
      {
        id: 'signs.level2',
        label: 'Признак происшествия',
        level: 2,
        required: hasLevel1,
        options: hasLevel1 ? [
          { id: referenceSignPath[1], label: 'Мусоропровод' },
          { id: 'sign.327035986dad45bf', label: 'Лифт' },
          { id: 'sign.7d0fbcce27226b00', label: 'Балкон' },
        ] : [],
      },
      {
        id: 'signs.level3',
        label: 'Уточнение признака',
        level: 3,
        required: hasLevel2,
        options: hasLevel2 ? [
          { id: referenceSignPath[2], label: 'Дым' },
          { id: 'sign.9e7097aa334c9add', label: 'Открытое пламя' },
        ] : [],
      },
    ],
    // Core exposes questions for records that continue the selected prefix.
    // For the reference scenario they become available after level 1.
    questions: hasLevel1 ? referenceQuestions : [],
  };
}
