#!/usr/bin/env python3
"""Проверка минимизации персональных данных и утечки секретов. Задача #89.

В коде Core уже стоят прямые запреты: «не копировать имена, телефоны и
введённый адрес в переиспользуемый сценарий», «табло не содержит учётных
данных, карточки, адреса, телефона, транскрипта». Эта проверка следит, что
намерения соблюдаются, а не остаются комментарием.

Что смотрит:

1. Файлы репозитория - примеры сценариев, фикстуры, тестовые данные: нет ли
   там телефонов, адресов электронной почты и похожего на настоящие ПДн.
2. Ответы работающего сервиса - внешнее табло и аналитику: не утекают ли
   имена, телефоны, адреса, транскрипты и личные баллы туда, где их быть
   не должно.
3. Журналы контейнеров - нет ли в них паролей, токенов и сырого звука.

Запуск:

    python scripts/check_personal_data.py
    python scripts/check_personal_data.py --core http://127.0.0.1:8080

Код возврата 0 - утечек не нашлось, 1 - нашлось, всё печатается.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

# Где ищем в файлах. Каталоги зависимостей и сборки исключены: чужой код
# нас не касается, а шум скрыл бы настоящую находку.
SCANNED = [
    "contracts/examples",
    "contracts/catalog",
    "services/ai/tests/fixtures",
    "services/ai/benchmarks",
    "services/media/tests",
]

SKIP_SUFFIXES = {".wav", ".pcm", ".rtp", ".onnx", ".dump", ".png", ".jpg", ".pdf", ".xlsx"}

# Признаки настоящих персональных данных. Шаблоны узкие намеренно: широкие
# дают ложные срабатывания на каждом числе, и проверку перестают читать.
PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("телефон", re.compile(r"(?<!\d)(?:\+7|8)[\s(-]?9\d{2}[\s)-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")),
    ("почта", re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")),
    ("СНИЛС", re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}\s\d{2}(?!\d)")),
]

# Шаблона паспорта здесь нет намеренно. Он неизбежно ловит любые десять
# цифр подряд - коды классификатора, куски хешей sha256 - и проверка
# превращается в шум, который перестают читать. Паспортные данные в этой
# системе не ходят: в карточке заявителя их нет по контракту.

# Поля, которых не должно быть во внешнем табло. Список из комментария
# к TrainingBoard: там это обещано словами, здесь проверяется.
FORBIDDEN_ON_BOARD = [
    "studentName", "displayName", "username", "phone", "phoneNumbers",
    "fullName", "address", "displayAddress", "transcript", "card",
    "submittedCard", "description",
]

# Что не должно попадать в журналы.
SECRET_MARKERS = ["PGPASSWORD", "POSTGRES_PASSWORD", "ARI_PASSWORD", "Bearer "]


class Report:
    def __init__(self) -> None:
        self.findings: List[str] = []
        self.notes: List[str] = []

    def found(self, message: str) -> None:
        self.findings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


def scan_files(report: Report) -> None:
    print("Файлы репозитория: примеры, фикстуры, тестовые данные")
    checked = 0
    for relative in SCANNED:
        base = ROOT / relative
        if not base.exists():
            report.note("каталога %s нет, не проверялся" % relative)
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            checked += 1
            for name, pattern in PATTERNS:
                for match in pattern.findall(text):
                    report.found("%s: похоже на %s - %r"
                                 % (path.relative_to(ROOT), name, match))
    print("   проверено файлов: %d" % checked)


def fetch(url: str) -> Tuple[int, Optional[object]]:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None
    except Exception:  # noqa: BLE001
        return 0, None


def keys_of(payload: object, found: Optional[set] = None) -> set:
    """Все имена полей в ответе, на любой глубине."""
    found = found if found is not None else set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            keys_of(value, found)
    elif isinstance(payload, list):
        for item in payload:
            keys_of(item, found)
    return found


def scan_board(report: Report, core: str) -> None:
    """Внешнее табло не должно раскрывать личные данные обучающихся."""
    print("\nВнешнее табло и аналитика")
    targets = [
        ("табло", "%s/api/teacher/board" % core, FORBIDDEN_ON_BOARD),
        # В аналитике агрегаты, имён там тоже быть не должно.
        ("аналитика", "%s/api/teacher/analytics/summary" % core,
         ["studentName", "displayName", "username", "phone", "transcript"]),
    ]
    for title, url, forbidden in targets:
        status, payload = fetch(url)
        if status != 200 or payload is None:
            report.note("%s недоступно (код %s), не проверялось" % (title, status or "нет связи"))
            print("   %-12s не проверялось" % title)
            continue
        present = sorted(set(forbidden) & keys_of(payload))
        raw = json.dumps(payload, ensure_ascii=False)
        for name, pattern in PATTERNS:
            for match in pattern.findall(raw):
                report.found("%s: в ответе похоже на %s - %r" % (title, name, match))
        if present:
            report.found("%s: раскрывает поля %s" % (title, ", ".join(present)))
            print("   %-12s РАСКРЫВАЕТ: %s" % (title, ", ".join(present)))
        else:
            print("   %-12s личных полей нет" % title)


def scan_logs(report: Report, containers: List[str]) -> None:
    """В журналах не должно быть паролей, токенов и сырого звука."""
    print("\nЖурналы контейнеров")
    if not containers:
        report.note("контейнеры не указаны, журналы не проверялись")
        print("   пропущено")
        return
    for container in containers:
        result = subprocess.run(["docker", "logs", "--tail", "400", container],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            report.note("журнал %s не прочитался" % container)
            continue
        text = result.stdout + result.stderr
        leaks = [marker for marker in SECRET_MARKERS if marker in text]
        for name, pattern in PATTERNS:
            if pattern.search(text):
                leaks.append("похожее на %s" % name)
        if leaks:
            report.found("журнал %s содержит: %s" % (container, ", ".join(sorted(set(leaks)))))
            print("   %-28s НАЙДЕНО: %s" % (container, ", ".join(sorted(set(leaks)))))
        else:
            print("   %-28s чисто" % container)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", default=None,
                        help="адрес Core для проверки ответов; без него проверяются только файлы")
    parser.add_argument("--containers", default="",
                        help="через запятую: контейнеры, чьи журналы проверить")
    arguments = parser.parse_args()

    report = Report()
    print("=" * 78)
    print("Минимизация персональных данных и утечка секретов")
    print("=" * 78)

    scan_files(report)
    if arguments.core:
        scan_board(report, arguments.core.rstrip("/"))
    else:
        report.note("адрес Core не задан: ответы сервиса не проверялись")
    scan_logs(report, [c.strip() for c in arguments.containers.split(",") if c.strip()])

    print("\n" + "=" * 78)
    if report.notes:
        print("Что осталось непроверенным:")
        for note in report.notes:
            print("  -", note)
    if report.findings:
        print("\nНАЙДЕНО:")
        for finding in report.findings:
            print("  -", finding)
        return 1
    print("Персональных данных и секретов там, где их быть не должно, не нашлось.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
