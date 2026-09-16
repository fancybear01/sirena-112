"""Сравнение адресов без придирок к форме записи.

Если сверять строки как есть, то "д. 21" и "дом 21" окажутся ошибкой, хотя
обучающийся написал верно. Оценка, которая придирается к сокращениям, быстро
теряет доверие, и её перестают читать.

Поэтому адрес разбирается на значимые части: название улицы и номера дома,
корпуса, подъезда. Служебные слова и город отбрасываются - в московской
системе-112 город и так один.

Разбор одинаковый для эталона и для ответа обучающегося. Даже если он где-то
неточен, обе стороны разбираются одним и тем же способом, поэтому сравнение
остаётся честным.
"""

import re
from typing import List, NamedTuple, Tuple

# Слова, которые ничего не уточняют: город в московской системе-112 один.
IGNORED = {"г", "город", "москва", "рф", "россия"}

# Тип улицы сам по себе не значим: важно её название.
STREET_LABELS = {
    "ул": "улица",
    "улица": "улица",
    "пр": "проспект",
    "просп": "проспект",
    "проспект": "проспект",
    "пер": "переулок",
    "переулок": "переулок",
    "наб": "набережная",
    "набережная": "набережная",
    "ш": "шоссе",
    "шоссе": "шоссе",
    "б": "бульвар",
    "бул": "бульвар",
    "бульвар": "бульвар",
    "пл": "площадь",
    "площадь": "площадь",
    "проезд": "проезд",
    "туп": "тупик",
}

# Эти слова важны вместе со следующим за ними номером.
NUMBER_LABELS = {
    "д": "дом",
    "дом": "дом",
    "вл": "владение",
    "владение": "владение",
    "к": "корпус",
    "корп": "корпус",
    "корпус": "корпус",
    "стр": "строение",
    "строение": "строение",
    "под": "подъезд",
    "подъезд": "подъезд",
    "кв": "квартира",
    "квартира": "квартира",
    "эт": "этаж",
    "этаж": "этаж",
}

_NON_LETTERS = re.compile(r"[^а-яa-z0-9]+")
# Операторы часто пишут слитно: к1, д21, п3. Разделяем букву и цифру, но
# только в этом порядке: "52я Парковая" трогать нельзя.
_GLUED_LABEL = re.compile(r"([а-яa-z])(\d)")


class AddressMatch(NamedTuple):
    """Результат сравнения: доля найденного и чего не хватило."""

    share: float
    missing: List[str]
    extra: List[str]


def _tokens(text: str) -> List[str]:
    lowered = text.lower().replace("ё", "е")
    spaced = _GLUED_LABEL.sub(r"\1 \2", _NON_LETTERS.sub(" ", lowered))
    return [token for token in spaced.split() if token]


def parse(text: str) -> List[Tuple[str, str]]:
    """Разбирает адрес на пары: значимая часть и как её назвать человеку.

    Например "Москва, ул. Берзарина, д. 21, корп. 1" превращается в
    [("берзарина", "улица Берзарина"), ("21", "дом 21"), ("1", "корпус 1")].
    """
    parts: List[Tuple[str, str]] = []
    pending_label = ""

    for token in _tokens(text):
        if token in IGNORED:
            continue

        if token in STREET_LABELS:
            pending_label = STREET_LABELS[token]
            continue
        if token in NUMBER_LABELS:
            pending_label = NUMBER_LABELS[token]
            continue

        readable = token if token.isdigit() else token.capitalize()
        parts.append((token, "{label} {value}".format(label=pending_label, value=readable).strip()))
        pending_label = ""

    return parts


def compare(expected: str, actual: str) -> AddressMatch:
    """Считает, какая доля эталонного адреса нашлась в ответе обучающегося.

    Каждая часть эталона засчитывается один раз: если в эталоне два номера "2",
    то и в ответе должны быть оба.
    """
    expected_parts = parse(expected or "")
    actual_values = [value for value, _ in parse(actual or "")]

    if not expected_parts:
        return AddressMatch(share=1.0, missing=[], extra=[])

    remaining = list(actual_values)
    missing: List[str] = []

    for value, readable in expected_parts:
        if value in remaining:
            remaining.remove(value)
        else:
            missing.append(readable)

    matched = len(expected_parts) - len(missing)
    return AddressMatch(
        share=round(matched / len(expected_parts), 3),
        missing=missing,
        extra=remaining,
    )
