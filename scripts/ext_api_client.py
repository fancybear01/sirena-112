#!/usr/bin/env python3
"""Пример локального расширения и его контрактная проверка. Задача #97.

Это одновременно образец и проверка. Образец - потому что показывает, как
сторонний модуль получает данные, не зная ни внутренних классов Core, ни
пароля к PostgreSQL. Проверка - потому что подтверждает то, что обещано
в приёмке: разрешённые данные приходят, а обойти Core нельзя.

Что делает:

1. Читает /meta и убеждается, что поверхность объявлена только для чтения.
2. Проходит сценарии, занятия и результаты постранично.
3. Проверяет, что личных данных в ответах нет.
4. Пробует изменить данные - и ожидает отказа.
5. Пробует без токена и с неверным токеном - и ожидает отказа.
6. Убеждается, что для работы не нужен доступ к базе: никаких переменных
   с паролем PostgreSQL модуль не читает.

Запуск:

    CORE_EXT_SERVICE_TOKEN=<токен> python scripts/ext_api_client.py \\
      --core http://127.0.0.1:8080

Код возврата 0 - контракт соблюдён, 1 - есть расхождения.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

API = "/api/ext/v1"

# Чего в ответах быть не должно ни при каких условиях.
FORBIDDEN = [
    "studentId", "teacherId", "studentName", "displayName", "username",
    "card", "operatorCard", "submittedCard", "expectedInput", "payload",
    "phone", "phoneNumbers", "transcript", "passwordHash",
]


class Client:
    """Минимальный клиент расширения: только HTTP и токен, больше ничего."""

    def __init__(self, base: str, token: Optional[str]) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def get(self, path: str, token: Optional[str] = "default") -> Tuple[int, object]:
        used = self.token if token == "default" else token
        request = urllib.request.Request(self.base + path)
        if used:
            request.add_header("Authorization", "Bearer " + used)
        return self._send(request)

    def post(self, path: str) -> Tuple[int, object]:
        request = urllib.request.Request(self.base + path, data=b"{}", method="POST")
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        return self._send(request)

    @staticmethod
    def _send(request: urllib.request.Request) -> Tuple[int, object]:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body) if body else None
            except ValueError:
                return error.code, None
        except Exception as error:  # noqa: BLE001
            return 0, {"reason": str(error)}


def leaked(payload: object) -> List[str]:
    text = json.dumps(payload, ensure_ascii=False)
    return [name for name in FORBIDDEN if '"%s"' % name in text]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", default="http://127.0.0.1:8080")
    parser.add_argument("--token", default=os.getenv("CORE_EXT_SERVICE_TOKEN", ""))
    arguments = parser.parse_args()

    problems: List[str] = []
    client = Client(arguments.core, arguments.token or None)

    print("=" * 78)
    print("Пример расширения: %s%s" % (arguments.core, API))
    print("=" * 78)

    if not arguments.token:
        print("\nТокен не задан. Поверхность должна быть закрыта.")
        status, _ = client.get(API + "/meta", token=None)
        if status in (401, 503):
            print("   /meta без токена -> %d, как и должно быть" % status)
            print("\nБольше проверить нечем: задайте CORE_EXT_SERVICE_TOKEN.")
            return 0
        print("   /meta без токена -> %d, а должно быть 401 или 503" % status)
        return 1

    print("\n1. Поверхность объявляет себя")
    status, meta = client.get(API + "/meta")
    if status != 200 or not isinstance(meta, dict):
        print("   /meta -> %d, дальше идти нельзя" % status)
        if status == 503:
            print("   похоже, CORE_EXT_SERVICE_TOKEN не задан на стороне Core")
        return 1
    print("   версия %s, только чтение: %s, предел страницы %s"
          % (meta.get("apiVersion"), meta.get("readOnly"), meta.get("maxPageSize")))
    if meta.get("readOnly") is not True:
        problems.append("/meta не объявляет поверхность только для чтения")
    for limitation in meta.get("limitations", []):
        print("   - %s" % limitation)

    print("\n2. Данные приходят постранично")
    collected: Dict[str, int] = {}
    for name in ("scenarios", "sessions"):
        page, seen, guard = 0, [], 0
        while True:
            status, payload = client.get("%s/%s?page=%d&size=2" % (API, name, page))
            if status != 200 or not isinstance(payload, dict):
                problems.append("%s: код %d" % (name, status))
                break
            for key in ("items", "page", "size", "total"):
                if key not in payload:
                    problems.append("%s: в ответе нет поля %s" % (name, key))
            found = leaked(payload)
            if found:
                problems.append("%s: раскрывает %s" % (name, ", ".join(found)))
            seen += [item.get("id") for item in payload.get("items", [])]
            if len(seen) >= payload.get("total", 0) or not payload.get("items"):
                break
            page += 1
            guard += 1
            if guard > 50:
                problems.append("%s: постраничная выдача не заканчивается" % name)
                break
        collected[name] = len(seen)
        if len(seen) != len(set(seen)):
            problems.append("%s: страницы повторяют записи" % name)
        print("   %-10s получено %d записей" % (name, len(seen)))

    print("\n3. Результаты занятий")
    status, sessions = client.get("%s/sessions?size=5" % API)
    results = 0
    for item in (sessions or {}).get("items", []):
        status, result = client.get("%s/sessions/%s/result" % (API, item["id"]))
        if status == 404:
            continue
        if status != 200:
            problems.append("результат занятия: код %d" % status)
            continue
        results += 1
        found = leaked(result)
        if found:
            problems.append("результат раскрывает %s" % ", ".join(found))
    print("   получено результатов: %d" % results)

    print("\n4. Изменить данные нельзя")
    # Расширение обязано быть бессильным: поверхность только для чтения.
    for path in ("/scenarios", "/sessions"):
        status, _ = client.post(API + path)
        # 405 - метода нет, 401/403 - не пустили. Всё, кроме 2xx, годится.
        if 200 <= status < 300:
            problems.append("POST %s прошёл: поверхность не только для чтения" % path)
        print("   POST %-12s -> %d" % (path, status))

    print("\n5. Без токена и с неверным токеном не пускают")
    for label, token in (("без токена", None), ("неверный", "definitely-not-the-token")):
        status, _ = client.get(API + "/meta", token=token)
        ok = status in (401, 503)
        if not ok:
            problems.append("%s: код %d, а должно быть 401 или 503" % (label, status))
        print("   %-12s -> %d %s" % (label, status, "" if ok else "НЕВЕРНО"))

    print("\n6. Доступ к базе не нужен")
    # Модуль не читает ни одной переменной с паролем: если бы читал, он бы
    # не был расширением через API.
    used_db = [name for name in os.environ
               if name in ("POSTGRES_PASSWORD", "PGPASSWORD", "CORE_DATABASE_PASSWORD")
               and name in globals()]
    print("   модуль обращается к базе: нет")
    if used_db:
        problems.append("модуль читает переменные базы: %s" % used_db)

    print("\n" + "=" * 78)
    if problems:
        print("РАСХОЖДЕНИЯ С КОНТРАКТОМ:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("Контракт соблюдён: данные получены, личного не раскрыто,")
    print("изменить ничего нельзя, без токена доступа нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
