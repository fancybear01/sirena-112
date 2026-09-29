#!/usr/bin/env python3
"""Сверка покрытия требований по фактам, а не по заголовкам. Задача #99.

Смысл в том, чтобы поймать два расхождения, которые иначе уезжают в сдачу:

1. Задача закрыта, но связать её с влитым изменением нельзя - ни `Closes #N`
   в описании PR, ни номера в сообщении коммита. Для приёмки, которая требует
   доказательство на каждое требование, это дыра: проверяющий не пройдёт
   от требования к коду.
2. Требование считается покрытым, потому что задачи под ним закрыты, хотя
   часть из них открыта.

Скрипт не проверяет требования по существу - это делают отдельные документы
и прогоны. Он сверяет состояние задач с историей репозитория.

Запуск:

    python scripts/check_coverage.py
    python scripts/check_coverage.py --json итог.json

Доступ к GitHub берётся из сохранённых учётных данных git. Без сети скрипт
печатает, что сверить не смог, и возвращает 1: молча делать вид, что всё
сошлось, нельзя.
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Dict, List, Optional

REPOSITORY = "fancybear01/sirena-112"

# Карта из задачи #99: требование финального ТЗ -> задачи, которые его несут.
REQUIREMENTS: Dict[str, List[int]] = {
    "АРМ-112, карточка, классификатор, ДДС, AI-оценка":
        [31, 32, 33, 34, 35, 36, 37, 38, 50, 55, 60, 61, 63, 65],
    "SIP/VoIP, STT/TTS, AI-абонент, запись, массовые вызовы":
        [9, 10, 11, 12, 13, 52, 53, 54, 66, 67, 68, 69, 70, 71, 72, 73, 74, 80, 87],
    "PostgreSQL, хранение, восстановление после перезапуска": [81, 90, 92],
    "ADMIN: учётки, роли, техсостояние, конфигурация": [82, 83, 88, 89, 95],
    "TEACHER: сценарии, назначение, мониторинг, отчёты": [55, 75, 76, 78, 84, 85, 86],
    "STUDENT: свои задания, карточка, таймер, история": [61, 63, 82, 85, 94],
    "Численные нефункциональные показатели": [80, 91, 92],
    "TLS, RBAC, ПДн, аудит, backup, мониторинг": [81, 82, 83, 88, 89, 90, 91, 92, 95],
    "Offline-контур, платформы, интерфейс, установка": [50, 63, 88, 91, 93, 94],
    "Форматы и источники данных": [32, 33, 77, 81, 87, 98],
    "Внутренний P2": [75, 76, 77, 78, 79, 80],
    "Опциональный блок ТЗ": [75, 76, 77, 94, 97],
    "Документация, презентация, сдача": [64, 65, 93, 96, 98],
}

# Показатели ТЗ и документ, где лежит замер. None означает, что замера нет.
NUMBERS = [
    ("отклик API p95 не больше 2 с", "docs/ai-load.md"),
    ("20 учебных занятий одновременно", "docs/ai-load.md"),
    ("VoIP one-way latency не больше 150 мс", None),
    ("100 одновременных пользователей", None),
    ("не меньше 100 операций записи в базу в секунду", None),
    ("формирование отчёта не дольше 30 с", None),
]


def token() -> Optional[str]:
    """Доступ к GitHub из сохранённых учётных данных git."""
    try:
        answer = subprocess.run(
            ["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    match = re.search(r"^password=(.+)$", answer, re.MULTILINE)
    return match.group(1) if match else None


def issues(auth: str) -> Dict[int, dict]:
    import urllib.request

    found: Dict[int, dict] = {}
    prs: List[dict] = []
    for page in range(1, 5):
        request = urllib.request.Request(
            "https://api.github.com/repos/%s/issues?state=all&per_page=100&page=%d"
            % (REPOSITORY, page),
            headers={"Authorization": "Bearer " + auth, "Accept": "application/vnd.github+json"},
        )
        batch = json.loads(urllib.request.urlopen(request, timeout=30).read())
        if not batch:
            break
        for item in batch:
            if "pull_request" in item:
                prs.append(item)
            else:
                found[item["number"]] = item

    # Чем задача связана с кодом: номер в описании или заголовке влитого PR.
    for pull in prs:
        if not pull.get("pull_request", {}).get("merged_at"):
            continue
        text = "%s %s" % (pull.get("body") or "", pull["title"])
        for number in set(int(value) for value in re.findall(r"#(\d{1,3})\b", text)):
            if number in found:
                found[number].setdefault("_proof", []).append("PR #%d" % pull["number"])
    return found


def history_mentions() -> Dict[int, str]:
    """Номера задач, упомянутые в истории main любым способом."""
    log = subprocess.run(
        ["git", "log", "origin/main", "--oneline", "-500"], capture_output=True, text=True
    ).stdout
    # Номер задачи в истории пишут по-разному: "(#107)", "issue 9", "67 issue".
    # Ловим все три, иначе проверка объявит сделанное несделанным.
    patterns = (r"#(\d{1,3})\b", r"\bissue\s+(\d{1,3})\b", r"\b(\d{1,3})\s+issue\b")
    mentions: Dict[int, str] = {}
    for line in log.splitlines():
        numbers = set()
        for pattern in patterns:
            numbers.update(int(value) for value in re.findall(pattern, line, re.IGNORECASE))
        for number in numbers:
            mentions.setdefault(number, line.split()[0])
    return mentions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=None, help="куда сложить итог машинно")
    arguments = parser.parse_args()

    auth = token()
    if not auth:
        print("Сверить не смогла: нет доступа к GitHub из учётных данных git.")
        print("Без состояния задач эта проверка бессмысленна, поэтому не притворяюсь.")
        return 1

    try:
        known = issues(auth)
    except Exception as error:  # noqa: BLE001
        print("Сверить не смогла: %s" % error)
        return 1

    mentions = history_mentions()
    for number, item in known.items():
        if number in mentions:
            item.setdefault("_proof", []).append("коммит %s" % mentions[number])

    print("=" * 78)
    print("Покрытие требований: задач %d, закрыто %d, открыто %d"
          % (len(known),
             sum(1 for i in known.values() if i["state"] == "closed"),
             sum(1 for i in known.values() if i["state"] == "open")))
    print("=" * 78)

    problems: List[str] = []
    summary = {}

    print("\nТребование -> состояние задач под ним")
    for requirement, numbers in REQUIREMENTS.items():
        unknown = [n for n in numbers if n not in known]
        opened = [n for n in numbers if known.get(n, {}).get("state") == "open"]
        untraced = [n for n in numbers
                    if known.get(n, {}).get("state") == "closed" and not known[n].get("_proof")]
        state = "НЕ ГОТОВО" if opened else ("без трассировки" if untraced else "готово")
        summary[requirement] = {"open": opened, "untraced": untraced, "state": state}
        print("   %-54s %s" % (requirement[:54], state))
        if opened:
            print("      открыты: %s" % ", ".join("#%d" % n for n in opened))
        if untraced:
            print("      закрыты без связи с кодом: %s" % ", ".join("#%d" % n for n in untraced))
        if unknown:
            problems.append("%s: задач %s нет в репозитории" % (requirement, unknown))

    print("\nЧисленные показатели ТЗ")
    for name, source in NUMBERS:
        print("   %-48s %s" % (name, source or "ЗАМЕРА НЕТ"))
        if source is None:
            problems.append("нет замера: %s" % name)

    untraced_all = sorted(n for n, i in known.items()
                          if i["state"] == "closed" and not i.get("_proof"))
    if untraced_all:
        print("\nЗакрыты, но связать с изменением нельзя: %s"
              % ", ".join("#%d" % n for n in untraced_all))
        problems.append("без трассировки закрыто задач: %d" % len(untraced_all))

    if arguments.json:
        with open(arguments.json, "w", encoding="utf-8") as handle:
            json.dump({"requirements": summary, "untraced": untraced_all},
                      handle, ensure_ascii=False, indent=2)
        print("\nитог сложен в %s" % arguments.json)

    print("\n" + "=" * 78)
    if problems:
        print("РАСХОЖДЕНИЯ, которые нельзя выдавать за готовое:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("Расхождений между задачами и кодом не нашлось.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
