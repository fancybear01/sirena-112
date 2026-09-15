"""Генерация сценариев: заглушка с фиксированной выдачей.

Каталог собран из реальных билетов ГБУ «Система 112», чтобы формат данных
проверялся на настоящих формулировках, а не на выдуманных примерах.
Настоящая генерация появится после подключения классификатора происшествий
и локальной модели, контракт при этом не меняется.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid5

from app.config import SERVICE_VERSION
from app.schemas.common import ResponseMeta
from app.schemas.generation import ScenarioGenerateRequest, ScenarioGenerateResponse
from app.schemas.scenario import (
    Caller,
    Category,
    GroundTruth,
    Rubric,
    RubricCriterion,
    Scenario,
)

# Фиксированное пространство имён, чтобы одинаковый запрос давал одинаковые id.
NAMESPACE = UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

# Базовая рубрика. Веса нормируются при оценке, поэтому здесь они условные.
BASE_CRITERIA: List[Dict[str, Any]] = [
    {
        "code": "GREETING",
        "description": "Представился и назвал службу в начале разговора",
        "weight": 1.0,
        "critical": False,
    },
    {
        "code": "ADDRESS",
        "description": "Установил точный адрес происшествия",
        "weight": 3.0,
        "critical": True,
    },
    {
        "code": "INCIDENT_TYPE",
        "description": "Верно определил тип происшествия",
        "weight": 3.0,
        "critical": True,
    },
    {
        "code": "VICTIMS",
        "description": "Уточнил наличие пострадавших",
        "weight": 2.0,
        "critical": False,
    },
    {
        "code": "SERVICES",
        "description": "Верно сформировал список оповещения служб",
        "weight": 2.0,
        "critical": False,
    },
    {
        "code": "TIMING",
        "description": "Уложился в норматив времени",
        "weight": 1.0,
        "critical": False,
    },
]

CATALOGUE: List[Dict[str, Any]] = [
    {
        "title": "Возгорание мусорного контейнера у станции",
        "category": Category.FIRE,
        "ground_truth": {
            "incident_type": "пожар: мусор",
            "ekp_code": "1010101",
            "signs": {
                "level1": "на улице",
                "level2": "мусор",
                "level3": "открытое пламя",
            },
            "address": "Москва, МЖД Киевская 1 км, д. 2, стр. 2",
            "required_services": ["Служба 101", "ДДС района"],
            "facts": {
                "callerName": "Сидоров Иван Сергеевич",
                "callerPhone": "916-126-34-71",
                "victims": "пострадавших нет",
                "openFlame": "да",
                "landmark": "рядом участковый пункт полиции",
            },
        },
        "caller": {
            "persona": "Спокойный мужчина средних лет, говорит по делу",
            "panic": 0.2,
            "trust": 0.7,
            "patience": 0.8,
            "background": "улица, шум поездов",
        },
    },
    {
        "title": "Задымление мусоропровода в жилом доме",
        "category": Category.FIRE,
        "ground_truth": {
            "incident_type": "задымление: мусоропровод",
            "ekp_code": "1050602",
            "signs": {
                "level1": "жилой дом",
                "level2": "мусоропровод",
                "level3": "дым",
            },
            "address": "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
            "required_services": ["Служба 101", "ДДС района", "МОЭК"],
            "facts": {
                "callerName": "Ким Олег Юрьевич",
                "callerPhone": "916-126-34-71",
                "victims": "пострадавших нет",
                "openFlame": "нет",
                "floors": "в доме 17 этажей",
                "callerFloor": "заявитель на 7 этаже",
                "intercom": "домофон 68",
            },
        },
        "caller": {
            "persona": "Встревоженный житель, торопится, перескакивает с темы",
            "panic": 0.6,
            "trust": 0.5,
            "patience": 0.6,
            "background": "подъезд, эхо",
        },
    },
    {
        "title": "ДТП с троллейбусом, есть пострадавшие",
        "category": Category.ACCIDENT,
        "ground_truth": {
            "incident_type": "ДТП с пострадавшими - общественный",
            "ekp_code": "2020500",
            "signs": {
                "level1": "ДТП пострадавшие",
                "level2": "Транспорт общественный",
            },
            "address": "Москва, Волгоградский проспект в сторону области, остановка «Завод Спецэлектрод»",
            "required_services": ["Служба 103", "Служба 102", "ЦОДД", "Мосгортранс"],
            "facts": {
                "callerName": "Иванова Елена Сергеевна",
                "callerPhone": "916-896-32-54",
                "victims": "3 пострадавших, не блокированы",
                "vehicles": "троллейбус маршрут 27, бортовой 11458, и ВАЗ-2115",
                "hazard": "течёт бензин",
            },
        },
        "caller": {
            "persona": "Очевидец на улице, взволнована, много деталей сразу",
            "panic": 0.7,
            "trust": 0.6,
            "patience": 0.5,
            "background": "проезжая часть, гудки",
        },
    },
]


def _select(category: Optional[Category]) -> List[Dict[str, Any]]:
    """Отбирает заготовки по теме занятия, сохраняя порядок каталога."""
    if category is None:
        return list(CATALOGUE)
    matching = [item for item in CATALOGUE if item["category"] == category]
    # Если под выбранную тему заготовки нет, отдаём каталог целиком:
    # преподавателю лучше получить черновик на правку, чем пустой список.
    return matching or list(CATALOGUE)


def generate(request: ScenarioGenerateRequest) -> ScenarioGenerateResponse:
    """Возвращает запрошенное количество сценариев, повторяя каталог по кругу."""
    source = _select(request.category)
    scenarios: List[Scenario] = []

    for index in range(request.count):
        item = source[index % len(source)]
        scenario_key = "{category}|{difficulty}|{seed}|{index}".format(
            category=request.category.value if request.category else "ANY",
            difficulty=request.difficulty.value,
            seed=request.seed,
            index=index,
        )
        scenarios.append(
            Scenario(
                id=uuid5(NAMESPACE, scenario_key),
                version=1,
                title=item["title"],
                category=item["category"],
                difficulty=request.difficulty,
                profile=request.profile,
                time_limit_seconds=request.time_limit_seconds,
                ground_truth=GroundTruth(**item["ground_truth"]),
                caller=Caller(**item["caller"]),
                rubric=Rubric(
                    criteria=[RubricCriterion(**criterion) for criterion in BASE_CRITERIA]
                ),
            )
        )

    return ScenarioGenerateResponse(
        scenarios=scenarios,
        meta=ResponseMeta(engine="mock", version=SERVICE_VERSION, deterministic=True),
    )
