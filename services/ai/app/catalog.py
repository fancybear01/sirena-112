"""Доступ к нормализованному каталогу классификатора.

Каталог собирается импортёром из официального XLSX и лежит в contracts.
Это единственный источник истины про признаки, вопросы и службы: ни Core,
ни AI не хранят свои копии этих значений.

AI читает каталог только для справки - чтобы показать преподавателю понятные
названия признаков и вопросов вместо идентификаторов. Маршрутизацию служб
AI не вычисляет: готовый результат приходит от Core.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

DEFAULT_CATALOG = "contracts/catalog/classifier-v046-11.json"


def _repository_root() -> Path:
    """Корень репозитория: три уровня выше services/ai/app."""
    return Path(__file__).resolve().parents[3]


class Catalog:
    """Справочники классификатора, загруженные в память."""

    def __init__(self, data: Dict) -> None:
        self.version: str = data.get("classifierVersion", "")
        self.source: Dict = data.get("source", {})
        self.services: Dict[str, str] = {
            item["id"]: item["displayName"] for item in data.get("services", [])
        }
        self.signs: Dict[str, Dict] = {item["id"]: item for item in data.get("signs", [])}
        self.questions: Dict[str, Dict] = {
            item["id"]: item for item in data.get("questions", [])
        }
        self.records: Dict[str, Dict] = {
            item["classifierCode"]: item for item in data.get("records", [])
        }

    def sign_label(self, sign_id: str) -> str:
        """Человеческое название признака; сам идентификатор как запасной вариант."""
        sign = self.signs.get(sign_id)
        return sign["label"] if sign else sign_id

    def sign_level(self, sign_id: str) -> Optional[int]:
        sign = self.signs.get(sign_id)
        return sign["level"] if sign else None

    def question_label(self, question_id: str) -> str:
        question = self.questions.get(question_id)
        return question["label"] if question else question_id

    def service_name(self, service_id: str) -> str:
        return self.services.get(service_id, service_id)


_cache: Dict[str, Optional[Catalog]] = {}


def load_catalog(path: Optional[str] = None) -> Optional[Catalog]:
    """Загружает каталог один раз и держит в памяти.

    Возвращает None, если файла нет. Сервис при этом продолжает работать:
    названия признаков в отчёте будут заменены идентификаторами, а расхождение
    версий отметится как неполнота эталона, а не как падение.
    """
    location = path or os.getenv("AI_CATALOG_PATH") or str(_repository_root() / DEFAULT_CATALOG)
    if location not in _cache:
        file = Path(location)
        _cache[location] = (
            Catalog(json.loads(file.read_text(encoding="utf-8"))) if file.exists() else None
        )
    return _cache[location]


def catalog_version() -> str:
    """Версия загруженного каталога или пустая строка, если каталога нет."""
    catalog = load_catalog()
    return catalog.version if catalog else ""
