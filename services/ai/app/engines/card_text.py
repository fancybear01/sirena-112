"""Сборка разбора текста карточки для преподавателя.

Движок text_review умеет отдельные проверки и ничего не знает про сценарий.
Здесь они складываются в один ответ: что проверяли, что получилось, чему
можно верить и чего разбор не умеет.
"""

from typing import List

from app.config import SERVICE_VERSION
from app.engines import text_review
from app.schemas.common import ResponseMeta
from app.schemas.text import TextFinding, TextReviewRequest, TextReviewResponse

# Короче этого описание считается отпиской, а не описанием обстоятельств.
MINIMUM_DESCRIPTION_WORDS = 5

# Ограничения перечисляются всегда, даже когда всё работает. Молчание здесь
# читалось бы как "разбор понимает текст целиком", а это неправда.
ALWAYS_TRUE_LIMITATIONS = [
    "Нейросети в разборе нет: сравниваются начальные формы слов. Одинаковый текст всегда даёт одинаковый вывод.",
    "Синонимы не распознаются: пересказ другими словами может быть отмечен как неполный.",
    "Смысловой вывод показывается как требующий проверки: на разметке он совпал с экспертом в 81 случае из 100, а простое сравнение слов - в 56.",
]


def looks_like_import_stub(reference: str) -> bool:
    """Похоже ли эталонное описание на то, что подставил импорт.

    Импорт складывает в сценарий строку вида "Учебный пример: <тип>" - это
    не описание обстоятельств, а повтор названия происшествия. Сравнивать
    с ней текст оператора нельзя: правильное описание получит FAILED за то,
    что в нём нет слов "учебный" и "пример".

    Признак грубый - двоеточие и мало слов, - но лучше грубого признака
    здесь только настоящие описания в каталоге, а их пока нет.
    """
    return ":" in reference and len(text_review.words(reference)) <= 6


def review(request: TextReviewRequest) -> TextReviewResponse:
    """Разбирает текст карточки и честно помечает, чему верить."""
    analyzer = text_review.morphology()
    expected = request.scenario.ground_truth.expected_input

    limitations: List[str] = list(ALWAYS_TRUE_LIMITATIONS)
    if not analyzer.available:
        limitations.append(
            "Словарь морфологии не установлен: грамотность не проверялась, "
            "смысл сравнивался по словам без разбора."
        )

    reference = expected.description or ""
    reference_is_stub = bool(reference) and looks_like_import_stub(reference)
    if reference_is_stub:
        limitations.append(
            "Эталонное описание сценария - заглушка импорта вида "
            "\"Учебный пример: <тип происшествия>\". Смысл по нему не проверялся: "
            "сравнение с такой строкой ругалось бы на правильные описания."
        )

    allowed = [reference, request.address_text or "", expected.address.display_address if expected.address else ""]

    meaning = (
        text_review.Finding(
            "MEANING",
            "NOT_CHECKED",
            "эталонное описание сценария - заглушка импорта, сравнивать не с чем",
        ).settle()
        if reference_is_stub
        else text_review.check_meaning(reference, request.description)
    )

    findings: List[text_review.Finding] = [
        meaning,
        text_review.check_spelling(request.description, allowed=allowed),
        text_review.check_mechanics(request.description),
        text_review.check_regulation(
            {
                "описание": bool((request.description or "").strip()),
                "адрес": bool((request.address_text or "").strip()),
                "пострадавшие": bool((request.victims_text or "").strip()),
            },
            MINIMUM_DESCRIPTION_WORDS,
            request.description,
        ),
        text_review.check_time(request.elapsed_seconds, request.scenario.time_limit_seconds),
    ]

    return TextReviewResponse(
        session_id=request.session_id,
        scenario_id=str(request.scenario.id),
        method="morphology" if analyzer.available else "words",
        limitations=limitations,
        findings=[
            TextFinding(
                code=finding.code,
                status=finding.status,
                explanation=finding.explanation,
                details=finding.details,
                confidence=finding.confidence,
                needs_teacher_check=finding.needs_teacher_check,
            )
            for finding in findings
        ],
        meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
    )
