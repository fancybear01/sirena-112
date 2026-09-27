"""Рекомендации преподавателю по типичным ошибкам группы.

AI не имеет доступа к базе и ничего про группу не помнит. Ошибки приходят
в запросе - их собирает Core из уже сохранённых отчётов. Здесь только счёт
и формулировка.

Главное правило: **не выдумывать факты.** Рекомендация опирается только на
код критерия и на то, в скольких занятиях он подвёл. Если критерий нам
незнаком, текст всё равно выдаётся - общий, без домыслов о содержании.
"""

from collections import Counter
from typing import Dict, List

from app.schemas.text import (
    GroupRecommendation,
    GroupRecommendationsRequest,
    GroupRecommendationsResponse,
)
from app.config import SERVICE_VERSION
from app.schemas.common import ResponseMeta

# Рекомендация показывается, если критерий подвёл хотя бы в этой доле занятий.
# Ниже - это единичный случай конкретного обучающегося, а не тема для группы.
GROUP_SHARE_FROM = 0.3

# Что советовать по каждому критерию рубрики. Это методика обучения, а не
# данные классификатора: названий служб и кодов происшествий здесь нет.
ADVICE: Dict[str, str] = {
    "GREETING": "Отработать начало разговора: представиться и назвать службу до первого вопроса",
    "SIGNS": "Разобрать путь признаков происшествия: группу выбирают до уточняющих вопросов",
    "QUESTIONS": "Повторить обязательные вопросы опросной карты, их пропускают чаще всего",
    "ADDRESS": "Потренировать сбор адреса: уточнять подъезд и ориентиры, а не только улицу",
    "VICTIMS": "Отработать вопрос о пострадавших и угрозе людям, его задают не всегда",
    "DESCRIPTION": "Показать, какие обстоятельства обязательно попадают в описание",
    "CLASSIFICATION": "Разобрать, как признаки карточки складываются в тип происшествия",
    "SERVICES": "Разобрать состав служб: кого вызывают обязательно, а кого по обстановке",
}


def _text_for(code: str, affected: int, total: int) -> str:
    advice = ADVICE.get(code)
    if advice is None:
        # Незнакомый критерий - не повод молчать и не повод фантазировать.
        return "Разобрать критерий %s: он подвёл в %d занятиях из %d" % (code, affected, total)
    return "%s. Подвёл в %d занятиях из %d" % (advice, affected, total)


def recommend(request: GroupRecommendationsRequest) -> GroupRecommendationsResponse:
    """Считает, какие критерии подводят группу чаще прочих."""
    limitations = [
        "Рекомендации посчитаны по присланным отчётам: своей истории у AI нет.",
        "Это подсказка, а не вывод об уровне группы. Текст можно менять и убирать.",
    ]

    total = request.sessions_total
    if not total or not request.errors:
        limitations.append("Данных мало: рекомендации не построены.")
        return GroupRecommendationsResponse(
            group_id=request.group_id,
            sessions_total=total,
            recommendations=[],
            limitations=limitations,
            meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
        )

    # Одно занятие с одним критерием считается один раз, даже если ошибок
    # в нём несколько: иначе один старательно проваленный критерий перевесит
    # всю группу.
    per_criterion: Dict[str, set] = {}
    for error in request.errors:
        per_criterion.setdefault(error.criterion_code, set()).add(error.session_id)

    counted = Counter({code: len(sessions) for code, sessions in per_criterion.items()})

    recommendations: List[GroupRecommendation] = []
    # Порядок задан явно: сначала по частоте, потом по коду. Без второго
    # ключа одинаково частые критерии выпадали бы вразнобой.
    for code, affected in sorted(counted.items(), key=lambda item: (-item[1], item[0])):
        share = affected / total
        if share < GROUP_SHARE_FROM:
            continue
        recommendations.append(
            GroupRecommendation(
                criterion_code=code,
                sessions_affected=affected,
                share=round(share, 3),
                text=_text_for(code, affected, total),
            )
        )

    if not recommendations:
        limitations.append(
            "Ни один критерий не подвёл чаще, чем в %d%% занятий: общей темы не видно."
            % round(GROUP_SHARE_FROM * 100)
        )

    return GroupRecommendationsResponse(
        group_id=request.group_id,
        sessions_total=total,
        recommendations=recommendations,
        limitations=limitations,
        meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
    )
