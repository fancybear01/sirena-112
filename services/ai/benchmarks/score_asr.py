"""Подсчёт точности распознавания по ключевым частям фразы.

Общий процент угаданных слов нам не подходит: если модель услышала
"двадцать один" вместо "21", формальная метрика засчитает ошибку, а для
оператора это одно и то же. Важно другое - попадут ли в карточку верные
улица, дом, корпус и подъезд.

Поэтому у каждой записи в reference.json задан список ключевых частей,
и точность считается по ним.

Запуск:

    python score_asr.py recognized.json

Формат recognized.json - словарь "имя файла": "распознанный текст":

    {
      "01_address_calm.wav": "берзарина двадцать один корпус один третий подъезд",
      "03_phone_panic.wav": "916 126 34 71"
    }
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

REFERENCE = Path(__file__).with_name("reference.json")

# Числительные, которые модели пишут то словами, то цифрами. Для оценки это
# одно и то же: в карточку всё равно попадёт число.
NUMERALS: Dict[str, str] = {
    "ноль": "0",
    "один": "1",
    "одна": "1",
    "первый": "1",
    "два": "2",
    "две": "2",
    "второй": "2",
    "три": "3",
    "третий": "3",
    "четыре": "4",
    "четвертый": "4",
    "пять": "5",
    "пятый": "5",
    "шесть": "6",
    "шестой": "6",
    "семь": "7",
    "седьмой": "7",
    "восемь": "8",
    "восьмой": "8",
    "девять": "9",
    "девятый": "9",
    "десять": "10",
    "двадцать": "20",
    "тридцать": "30",
    "сорок": "40",
    "пятьдесят": "50",
    "шестьдесят": "60",
    "семьдесят": "70",
    "восемьдесят": "80",
    "девяносто": "90",
    "сто": "100",
}

_NON_LETTERS = re.compile(r"[^а-яa-z0-9]+")


def normalize(text: str) -> str:
    """Приводит текст к виду, в котором можно искать ключевые части."""
    lowered = text.lower().replace("ё", "е")
    words = _NON_LETTERS.sub(" ", lowered).split()
    return " ".join(NUMERALS.get(word, word) for word in words)


def _number_variants(words: List[str]) -> List[str]:
    """Достраивает числа, произнесённые по частям.

    Модель может выдать "двадцать один" вместо "21" или "девять один шесть"
    вместо "916". Для оператора это одно и то же число, поэтому к найденным
    словам добавляются сумма и склейка каждой цепочки цифр подряд.
    """
    variants: List[str] = []
    run: List[int] = []

    def flush() -> None:
        for start in range(len(run)):
            for end in range(start + 1, len(run) + 1):
                chunk = run[start:end]
                if len(chunk) < 2:
                    continue
                variants.append(str(sum(chunk)))
                variants.append("".join(str(value) for value in chunk))
        run.clear()

    for word in words:
        if word.isdigit():
            run.append(int(word))
        else:
            flush()
    flush()
    return variants


def _found(part: str, recognized: str) -> bool:
    """Ключевая часть засчитывается, если все её слова есть в распознанном.

    Порядок не важен: "корпус 1" и "1 корпус" одинаково годятся. Слитное
    написание тоже: "спец электрод" засчитывается за "спецэлектрод".
    """
    words = recognized.split()
    available = set(words) | set(_number_variants(words))
    glued = "".join(words)

    return all(
        word in available or word in glued for word in normalize(part).split()
    )


def main(path: str) -> int:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    recognized = json.loads(Path(path).read_text(encoding="utf-8"))

    total_parts = total_hits = 0
    rows: List[str] = []

    for item in reference["items"]:
        name = item["file"]
        if name not in recognized:
            rows.append("%-28s пропущен" % name)
            continue

        text = normalize(recognized[name])
        missed = [part for part in item["keyParts"] if not _found(part, text)]
        hits = len(item["keyParts"]) - len(missed)

        total_parts += len(item["keyParts"])
        total_hits += hits
        rows.append(
            "%-28s %d/%d%s"
            % (name, hits, len(item["keyParts"]),
               "   не расслышано: " + ", ".join(missed) if missed else "")
        )

    print("\n".join(rows))
    if total_parts:
        print("\nитого %d/%d ключевых частей, точность %.0f%%"
              % (total_hits, total_parts, total_hits / total_parts * 100))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1]))
