import type { ScenarioCategory } from './types';

const categoryLabels: Record<ScenarioCategory, string> = {
  FIRE: 'Пожар',
  ACCIDENT: 'Дорожное происшествие',
  EXPLOSION: 'Взрыв',
  EXPLOSION_THREAT: 'Угроза взрыва',
  COLLAPSE: 'Обрушение',
  COLLAPSE_THREAT: 'Угроза обрушения',
  NATURAL_HAZARD: 'Природная опасность',
  ENVIRONMENT: 'Экологическое происшествие',
  HYDRAULIC_FACILITY: 'Авария на гидросооружении',
  INDUSTRIAL_ACCIDENT: 'Промышленная авария',
  HAZMAT_THREAT: 'Угроза опасных веществ',
  TRANSPORT_FACILITY: 'Транспортный объект',
  GAS: 'Газовая авария',
  UTILITY: 'Коммунальная авария',
  PUBLIC_ORDER: 'Нарушение общественного порядка',
  ROAD_CONDITION: 'Дорожная обстановка',
  PERSON_AT_RISK: 'Человек в опасности',
  CHILD_AT_RISK: 'Ребёнок в опасности',
  DEATH: 'Смерть человека',
  SOCIAL_AID: 'Социальная помощь',
  ANIMAL: 'Животное',
  MEDICAL: 'Медицинская помощь',
  OTHER: 'Другое',
};

export function getScenarioCategoryLabel(category: ScenarioCategory): string {
  return categoryLabels[category];
}
