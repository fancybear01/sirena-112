#!/usr/bin/env python3
"""Сравнение разбора текста с экспертной разметкой. Задача #86.

Считает три вещи:

1. Насколько наш разбор совпадает с разметкой по смыслу, грамотности
   и механике.
2. Насколько с ней совпадает простое правило - сравнение слов без разбора.
   Без этого сравнения нельзя утверждать, что морфология что-то даёт.
3. На каких примерах разбор ошибается. Они печатаются целиком: отчёт без
   разбора ошибок ничего не стоит.

Сети не требует, модели не качает. Запуск:

    .venv/bin/python benchmarks/text_review/score_text.py
    .venv/bin/python benchmarks/text_review/score_text.py --json итог.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.engines import text_review  # noqa: E402

DATASET = Path(__file__).resolve().parent / "dataset.json"

# Половина разметки, на которой подбираются пороги. Вторая половина остаётся
# нетронутой: темы в ней другие, и по ней видно, работает ли разбор на том,
# чего он не видел. Подбирать и мерить на одном наборе - это обманывать себя.
SELECTION_TOPICS = ("задымление в мусоропроводе", "ДТП без пострадавших")

# Сетка перебора порогов. Мелкий шаг тут не нужен: разметки тридцать четыре
# примера, и точность порога больше пяти процентов будет самообманом.
GRID = [round(value / 20, 2) for value in range(1, 20)]


def meaning_share(case: Dict, method: str) -> float:
    """Доля отражённых обстоятельств. Два способа посчитать одно и то же."""
    if not case["submitted"].strip():
        return 0.0
    if method == "lemmas":
        wanted = text_review.meaningful_lemmas(case["reference"])
        if not wanted:
            return 1.0
        got = text_review.meaningful_lemmas(case["submitted"])
        return (len(wanted) - len(wanted - got)) / len(wanted)
    return text_review.baseline_meaning(case["reference"], case["submitted"])


def meaning_verdict(case: Dict, method: str, passed_from: float, partial_from: float) -> str:
    if not case["submitted"].strip():
        return "FAILED"
    return text_review.meaning_status(meaning_share(case, method), passed_from, partial_from)


def pick_thresholds(cases: List[Dict], method: str) -> Tuple[float, float, float]:
    """Подбирает пороги на переданной половине разметки.

    Возвращает верхний порог, нижний и макро-F1, с которым они выбраны.
    """
    best = (0.0, 0.0, -1.0)
    for upper in GRID:
        for lower in GRID:
            if lower > upper:
                continue
            pairs = [
                (case["expert"]["meaning"], meaning_verdict(case, method, upper, lower))
                for case in cases
            ]
            score = macro_f1(pairs)
            if score > best[2]:
                best = (upper, lower, score)
    return best


def other_verdicts(case: Dict) -> Dict[str, str]:
    """Грамотность и механика: порогов тут нет, вердикт прямой."""
    spelling = text_review.check_spelling(case["submitted"], allowed=[case["reference"]])
    mechanics = text_review.check_mechanics(case["submitted"])
    return {
        "spelling": "PASSED" if spelling.status in ("PASSED", "NOT_CHECKED") else "FAILED",
        "mechanics": "PASSED" if mechanics.status in ("PASSED", "NOT_CHECKED") else "FAILED",
    }


def confusion(pairs: List[Tuple[str, str]], positive: str) -> Dict[str, float]:
    """Точность, полнота и F1 для одного класса.

    Считается по-честному: положительным считается конкретный класс,
    остальные - отрицательными. Для трёх классов смысла это делается
    отдельно по каждому.
    """
    true_positive = sum(1 for expert, got in pairs if expert == positive and got == positive)
    false_positive = sum(1 for expert, got in pairs if expert != positive and got == positive)
    false_negative = sum(1 for expert, got in pairs if expert == positive and got != positive)

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "support": true_positive + false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def accuracy(pairs: List[Tuple[str, str]]) -> float:
    return sum(1 for expert, got in pairs if expert == got) / len(pairs) if pairs else 0.0


def macro_f1(pairs: List[Tuple[str, str]]) -> float:
    """Среднее F1 по трём классам.

    Пороги подбираются именно по этому числу, а не по точности. На нашей
    разметке классы неравны: PASSED почти половина. Подбор по точности
    выбирал вырожденный порог, при котором почти всё объявляется полным
    описанием: точность вырастала, а PARTIAL перестал находиться вовсе.
    """
    scores = [confusion(pairs, label)["f1"] for label in ("PASSED", "PARTIAL", "FAILED")]
    return sum(scores) / len(scores)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--json", type=Path, default=None, help="куда сложить итог машинно")
    arguments = parser.parse_args()

    data = json.loads(arguments.dataset.read_text(encoding="utf-8"))
    cases = data["cases"]

    analyzer = text_review.morphology()
    print("=" * 78)
    print("Разбор текста против экспертной разметки")
    print("примеров: %d | морфология: %s" % (len(cases), "есть" if analyzer.available else "НЕТ"))
    if not analyzer.available:
        print("ВНИМАНИЕ: словаря нет, грамотность не проверяется, смысл считается грубо.")
    print("=" * 78)

    selection = [case for case in cases if case["topic"] in SELECTION_TOPICS]
    holdout = [case for case in cases if case["topic"] not in SELECTION_TOPICS]

    print("\nПодбор порогов на половине разметки")
    print("   подбор: %d примеров (%s)" % (len(selection), ", ".join(SELECTION_TOPICS)))
    print("   замер : %d примеров, темы другие" % len(holdout))

    chosen: Dict[str, Tuple[float, float, float]] = {}
    for method in ("lemmas", "words"):
        upper, lower, score = pick_thresholds(selection, method)
        chosen[method] = (upper, lower, score)
        print("   %-8s пороги %.2f и %.2f, точность на подборе %.2f"
              % (method, upper, lower, score))

    print("\nЗамер на отложенной половине")
    print("   %-28s %-10s %-10s %s" % ("способ", "точность", "макро-F1", "примеров"))
    holdout_pairs: Dict[str, List[Tuple[str, str]]] = {}
    for method, title in (("lemmas", "разбор по начальным формам"), ("words", "сравнение слов как есть")):
        upper, lower, _ = chosen[method]
        holdout_pairs[method] = [
            (case["expert"]["meaning"], meaning_verdict(case, method, upper, lower))
            for case in holdout
        ]
        print("   %-28s %-10.2f %-10.2f %d" % (title, accuracy(holdout_pairs[method]),
                                                    macro_f1(holdout_pairs[method]), len(holdout)))

    print("\nСмысл на отложенной половине, по классам")
    print("   %-10s %-9s %-10s %-9s %s" % ("класс", "примеров", "точность", "полнота", "F1"))
    for label in ("PASSED", "PARTIAL", "FAILED"):
        metrics = confusion(holdout_pairs["lemmas"], label)
        print("   %-10s %-9d %-10.2f %-9.2f %.2f"
              % (label, metrics["support"], metrics["precision"], metrics["recall"], metrics["f1"]))

    # Грамотность и механика порогов не имеют, поэтому считаются на всём наборе.
    other_pairs: Dict[str, List[Tuple[str, str]]] = {"spelling": [], "mechanics": []}
    for case in cases:
        got = other_verdicts(case)
        for check in other_pairs:
            other_pairs[check].append((case["expert"][check], got[check]))

    print("\nГрамотность и механика, весь набор")
    for check in ("spelling", "mechanics"):
        metrics = confusion(other_pairs[check], "FAILED")
        print("   %-12s точность %.2f полнота %.2f F1 %.2f (плохих примеров %d), совпадение %.2f"
              % (check, metrics["precision"], metrics["recall"], metrics["f1"],
                 metrics["support"], accuracy(other_pairs[check])))

    upper, lower, _ = chosen["lemmas"]
    mistakes: List[Dict] = []
    for case in cases:
        got = dict(other_verdicts(case))
        got["meaning"] = meaning_verdict(case, "lemmas", upper, lower)
        wrong = [check for check in ("meaning", "spelling", "mechanics")
                 if case["expert"][check] != got[check]]
        if wrong:
            mistakes.append({"case": case, "got": got, "wrong": wrong})

    print("\nОшибки разбора: %d из %d примеров" % (len(mistakes), len(cases)))
    for mistake in mistakes:
        case = mistake["case"]
        отложен = case["topic"] not in SELECTION_TOPICS
        print("\n   %s (%s)%s" % (case["id"], case["topic"], ", отложенная половина" if отложен else ""))
        print("      текст    : %s" % (case["submitted"] or "<пусто>"))
        print("      эксперт  : %s" % case["comment"])
        for check in mistake["wrong"]:
            print("      %-9s: ждали %s, получили %s"
                  % (check, case["expert"][check], mistake["got"][check]))

    summary = {
        "cases": len(cases),
        "morphology": analyzer.available,
        "selection_topics": list(SELECTION_TOPICS),
        "thresholds": {method: {"passedFrom": value[0], "partialFrom": value[1],
                                "selectionMacroF1": value[2]}
                       for method, value in chosen.items()},
        "holdout": {
            "cases": len(holdout),
            "accuracy": {method: accuracy(pairs) for method, pairs in holdout_pairs.items()},
            "macroF1": {method: macro_f1(pairs) for method, pairs in holdout_pairs.items()},
            "meaning_by_class": {
                label: confusion(holdout_pairs["lemmas"], label)
                for label in ("PASSED", "PARTIAL", "FAILED")
            },
        },
        "whole_set": {
            check: {
                "accuracy": accuracy(other_pairs[check]),
                "failed_class": confusion(other_pairs[check], "FAILED"),
            }
            for check in ("spelling", "mechanics")
        },
        "mistakes": [
            {"id": m["case"]["id"], "wrong": m["wrong"], "got": m["got"]} for m in mistakes
        ],
    }

    if arguments.json:
        arguments.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\nитог сложен в %s" % arguments.json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
