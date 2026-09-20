"""Сценарии берутся из общего каталога, а не из собственного списка.

Раньше здесь лежал свой набор сценариев с руками выписанными службами.
После появления официального классификатора это стало опасно: Core считал
маршрутизацию по каталогу, а AI сверял с собственной копией, и расхождение
было вопросом времени.

Теперь сценарии читаются из contracts/examples - тех же файлов, что использует
Core. Службы, код классификатора и признаки приходят оттуда как есть.
AI добавляет к ним только характер абонента: это поведение, а не факты,
и в каталоге ему не место.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from app.config import SERVICE_VERSION
from app.schemas.common import ResponseMeta
from app.schemas.generation import ScenarioGenerateRequest, ScenarioGenerateResponse
from app.engines.rubric import ensure_rubric
from app.schemas.scenario import Caller, Category, Scenario

DEFAULT_SCENARIOS = "contracts/examples"

# Характер звонящего подбирается по теме происшествия. Фактов здесь нет:
# всё содержательное берётся из эталона сценария.
PERSONA_BY_CATEGORY: Dict[Category, Dict] = {
    Category.FIRE: {
        "persona": "Встревоженный житель, торопится, перескакивает с темы",
        "panic": 0.6,
        "trust": 0.5,
        "patience": 0.6,
        "background": "подъезд, эхо",
    },
    Category.ACCIDENT: {
        "persona": "Очевидец на улице, взволнован, много деталей сразу",
        "panic": 0.7,
        "trust": 0.6,
        "patience": 0.5,
        "background": "проезжая часть, гудки",
    },
    Category.MEDICAL: {
        "persona": "Родственник пострадавшего, напуган, говорит сбивчиво",
        "panic": 0.8,
        "trust": 0.6,
        "patience": 0.4,
        "background": "квартира, тихо",
    },
}

DEFAULT_PERSONA = {
    "persona": "Заявитель, говорит по делу, но нервничает",
    "panic": 0.5,
    "trust": 0.5,
    "patience": 0.6,
    "background": "улица",
}

_cache: Dict[str, List[Scenario]] = {}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _scenarios_dir() -> Path:
    location = os.getenv("AI_SCENARIOS_PATH")
    return Path(location) if location else _repository_root() / DEFAULT_SCENARIOS


def _prepare(scenario: Scenario) -> Scenario:
    """Дополняет сценарий каталога тем, чего в классификаторе нет.

    Каталог описывает происшествие, но ничего не знает ни про характер
    звонящего, ни про то, как занятие оценивается. И то и другое - наша часть.
    """
    prepared = ensure_rubric(scenario)
    if prepared.caller is not None:
        return prepared
    profile = PERSONA_BY_CATEGORY.get(prepared.category, DEFAULT_PERSONA)
    return prepared.model_copy(update={"caller": Caller(**profile)})


def load_scenarios(directory: Optional[Path] = None) -> List[Scenario]:
    """Читает сценарии каталога один раз и держит в памяти.

    Порядок задан именами файлов, поэтому выдача воспроизводима.
    """
    path = directory or _scenarios_dir()
    key = str(path)
    if key not in _cache:
        files = sorted(path.glob("scenario-*.json")) if path.exists() else []
        _cache[key] = [
            _prepare(Scenario.model_validate(json.loads(file.read_text(encoding="utf-8"))))
            for file in files
        ]
    return _cache[key]


def _select(request: ScenarioGenerateRequest, scenarios: List[Scenario]) -> List[Scenario]:
    """Отбирает сценарии по теме и сложности занятия."""
    chosen = [s for s in scenarios if request.category is None or s.category == request.category]
    if request.difficulty is not None:
        narrowed = [s for s in chosen if s.difficulty == request.difficulty]
        # Если под выбранную сложность ничего нет, отдаём то, что есть по теме:
        # преподавателю полезнее черновик на правку, чем пустой список.
        chosen = narrowed or chosen
    return chosen or list(scenarios)


def generate(request: ScenarioGenerateRequest) -> ScenarioGenerateResponse:
    """Возвращает сценарии каталога, подходящие под запрос преподавателя.

    Ничего не сочиняет: идентификаторы, признаки и службы остаются теми же,
    что у Core. Поле seed только сдвигает начало выборки, чтобы на повторных
    занятиях выпадали разные сценарии.
    """
    available = _select(request, load_scenarios())
    if not available:
        return ScenarioGenerateResponse(
            scenarios=[],
            meta=ResponseMeta(engine="catalog", version=SERVICE_VERSION, deterministic=True),
        )

    offset = request.seed % len(available)
    picked = [available[(offset + index) % len(available)] for index in range(request.count)]

    return ScenarioGenerateResponse(
        scenarios=picked,
        meta=ResponseMeta(engine="catalog", version=SERVICE_VERSION, deterministic=True),
    )
