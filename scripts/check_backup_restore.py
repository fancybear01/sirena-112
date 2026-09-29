#!/usr/bin/env python3
"""Проверка «данные -> backup -> отдельный экземпляр -> restore -> сверка».

Приёмка задачи #90 требует не скрипт создания архива, а доказанное
восстановление с протоколом сравнения. Этот скрипт его и делает.

Рабочую базу не трогает разрушительно: только добавляет одну помеченную
строку, чтобы было видно, что в дамп попали свежие данные. Восстановление
идёт в отдельный контейнер на свободном порту, который в конце удаляется.

Что сверяется после восстановления:

- версия схемы: миграции Flyway совпадают по составу и контрольным суммам;
- количество строк в таблицах занятий, отчётов, сценариев, учётных записей
  и журнала аудита;
- помеченная строка на месте - значит дамп снят после её появления,
  а не взят старый файл;
- кодировка базы.

Запуск (рабочая база должна быть поднята):

    python scripts/check_backup_restore.py

Код возврата 0 - восстановление подтверждено, 1 - нет, причина печатается.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

# Таблицы, по которым сверяем содержимое. Список намеренно явный: молчаливое
# "сравним все таблицы" скрыло бы пропажу таблицы целиком.
TABLES = [
    "scenarios",
    "training_sessions",
    "session_reports",
    "service_assignments",
    "auth_accounts",
    "auth_audit",
    "flyway_schema_history",
]

IMAGE = "postgres:16-alpine"
TEMP_CONTAINER = "sirena-backup-check"
TEMP_DB = "sirena112_restore_check"


def run(command: List[str], stdin: Optional[str] = None, timeout: int = 120) -> Tuple[int, str, str]:
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def psql(container: str, database: str, user: str, query: str) -> str:
    code, out, err = run(
        ["docker", "exec", "-i", container, "psql", "-U", user, "-d", database, "-tAc", query]
    )
    if code != 0:
        raise RuntimeError("psql в %s: %s" % (container, err.strip()[:200]))
    return out.strip()


def counts(container: str, database: str, user: str) -> Dict[str, Optional[int]]:
    """Число строк по таблицам. None означает, что таблицы нет."""
    result: Dict[str, Optional[int]] = {}
    for table in TABLES:
        exists = psql(container, database, user,
                      "SELECT to_regclass('public.%s') IS NOT NULL" % table)
        if exists != "t":
            result[table] = None
            continue
        result[table] = int(psql(container, database, user, "SELECT count(*) FROM %s" % table))
    return result


def schema_fingerprint(container: str, database: str, user: str) -> str:
    """Состав и контрольные суммы миграций: по ним видно совместимость схемы.

    Таблицы миграций может не быть - например, если Core к базе ещё не
    подключался. Это не повод падать: сравнение двух одинаковых "нет истории"
    тоже осмысленно, а вот молчаливое исключение спрятало бы проверку.
    """
    present = psql(container, database, user,
                   "SELECT to_regclass('public.flyway_schema_history') IS NOT NULL")
    if present != "t":
        return "нет истории миграций"
    return psql(
        container, database, user,
        "SELECT coalesce(string_agg(version || ':' || coalesce(checksum::text, '-'), ',' "
        "ORDER BY installed_rank), 'история пуста') FROM flyway_schema_history",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="sirena-full-postgres-1",
                        help="контейнер рабочей базы")
    parser.add_argument("--database", default="sirena112")
    parser.add_argument("--user", default="sirena112")
    parser.add_argument("--password", default="sirena112-local")
    parser.add_argument("--backup-dir", default="/tmp/sirena-backup-check",
                        help="каталог для дампа на хосте")
    arguments = parser.parse_args()

    problems: List[str] = []
    marker = "проверка восстановления %s" % uuid.uuid4()

    print("=" * 78)
    print("Проверка резервного копирования и восстановления")
    print("=" * 78)

    code, out, _ = run(["docker", "inspect", "-f", "{{.State.Running}}", arguments.container])
    if code != 0 or out.strip() != "true":
        print("рабочая база не запущена: контейнер %s" % arguments.container)
        print("подними стек и повтори; притворяться, что проверка прошла, нельзя")
        return 1

    # Пока Core не применил миграции, в базу лезть нельзя. Любая своя таблица
    # в непустой схеме без истории Flyway ломает старт Core: он отказывается
    # мигрировать поверх чужих объектов. Проверено на себе - первый прогон
    # этого скрипта уложил Core именно так.
    if schema_fingerprint(arguments.container, arguments.database, arguments.user) \
            == "нет истории миграций":
        print("В базе нет истории миграций Flyway: Core к ней ещё не подключался.")
        print("Сначала подними Core, иначе проверка сломает старт приложения.")
        return 1

    # 1. Помеченная строка. Таблица своя, рабочие данные не трогаем.
    print("\n1. Кладу в рабочую базу помеченную строку")
    psql(arguments.container, arguments.database, arguments.user,
         "CREATE TABLE IF NOT EXISTS backup_check (id uuid PRIMARY KEY, note text, "
         "created_at timestamptz NOT NULL DEFAULT now())")
    psql(arguments.container, arguments.database, arguments.user,
         "INSERT INTO backup_check (id, note) VALUES ('%s', '%s')" % (uuid.uuid4(), marker))
    print("   метка: %s" % marker)

    before = counts(arguments.container, arguments.database, arguments.user)
    schema_before = schema_fingerprint(arguments.container, arguments.database, arguments.user)
    encoding_before = psql(arguments.container, arguments.database, arguments.user,
                           "SELECT current_setting('server_encoding')")

    # 2. Backup тем же скриптом, который работает по расписанию.
    print("\n2. Снимаю дамп рабочим скриптом")
    run(["mkdir", "-p", arguments.backup_dir])
    code, out, err = run([
        "docker", "run", "--rm",
        "--network", "container:%s" % arguments.container,
        "-v", "%s:/backups" % arguments.backup_dir,
        "-v", "%s/scripts/backup_postgres.sh:/backup.sh:ro" % subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip(),
        "-e", "POSTGRES_HOST=127.0.0.1",
        "-e", "POSTGRES_DB=%s" % arguments.database,
        "-e", "POSTGRES_USER=%s" % arguments.user,
        "-e", "PGPASSWORD=%s" % arguments.password,
        IMAGE, "sh", "/backup.sh",
    ], timeout=300)
    print("   " + (out.strip().replace("\n", "\n   ") or err.strip()[:200]))
    if code != 0:
        print("дамп не снялся")
        return 1

    code, listing, _ = run(["sh", "-c", "ls -1t %s/sirena112-*.dump | head -1" % arguments.backup_dir])
    dump = listing.strip()
    if not dump:
        print("файла дампа нет")
        return 1
    print("   файл: %s" % dump.split("/")[-1])

    status_path = "%s/last-backup.json" % arguments.backup_dir
    try:
        status = json.load(open(status_path, encoding="utf-8"))
        print("   состояние: %s, %s" % (status["result"], status["message"]))
        if status["result"] != "ok":
            problems.append("скрипт сообщил о неудаче: %s" % status["message"])
    except Exception as error:  # noqa: BLE001
        problems.append("файл состояния не читается: %s" % error)

    # 3. Отдельный экземпляр. Рабочий не затрагиваем совсем.
    print("\n3. Поднимаю чистый экземпляр PostgreSQL")
    run(["docker", "rm", "-f", TEMP_CONTAINER])
    code, _, err = run([
        "docker", "run", "-d", "--name", TEMP_CONTAINER,
        "-e", "POSTGRES_PASSWORD=%s" % arguments.password,
        "-e", "POSTGRES_USER=%s" % arguments.user,
        "-e", "POSTGRES_DB=postgres",
        "-v", "%s:/backups:ro" % arguments.backup_dir,
        IMAGE,
    ])
    if code != 0:
        print("не поднялся: %s" % err.strip()[:200])
        return 1

    try:
        ready = False
        for _ in range(60):
            code, _, _ = run(["docker", "exec", TEMP_CONTAINER, "pg_isready",
                              "-U", arguments.user, "-d", "postgres"])
            if code == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            print("чистый экземпляр не ответил")
            return 1
        print("   поднялся, контейнер %s" % TEMP_CONTAINER)

        # 4. Восстановление рабочим скриптом.
        print("\n4. Восстанавливаю дамп")
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True).stdout.strip()
        run(["docker", "cp", "%s/scripts/restore_postgres.sh" % root,
             "%s:/restore.sh" % TEMP_CONTAINER])
        code, out, err = run([
            "docker", "exec",
            "-e", "POSTGRES_HOST=127.0.0.1",
            "-e", "POSTGRES_USER=%s" % arguments.user,
            "-e", "PGPASSWORD=%s" % arguments.password,
            "-e", "RESTORE_DB=%s" % TEMP_DB,
            TEMP_CONTAINER, "sh", "/restore.sh", "/backups/%s" % dump.split("/")[-1],
        ], timeout=300)
        print("   " + (out.strip().replace("\n", "\n   ") or err.strip()[:300]))
        if code != 0:
            problems.append("восстановление завершилось с ошибкой")
            print("\nПРОТОКОЛ: восстановление не удалось")
            return 1

        # 5. Протокол сравнения.
        print("\n5. Сверяю восстановленное с исходным")
        after = counts(TEMP_CONTAINER, TEMP_DB, arguments.user)
        schema_after = schema_fingerprint(TEMP_CONTAINER, TEMP_DB, arguments.user)
        encoding_after = psql(TEMP_CONTAINER, TEMP_DB, arguments.user,
                              "SELECT current_setting('server_encoding')")

        print("   %-24s %-10s %-10s %s" % ("таблица", "было", "стало", "итог"))
        for table in TABLES:
            source, restored = before.get(table), after.get(table)
            if source is None and restored is None:
                verdict = "таблицы нет в обеих"
            elif source == restored:
                verdict = "совпало"
            else:
                verdict = "РАСХОЖДЕНИЕ"
                problems.append("%s: было %s, стало %s" % (table, source, restored))
            print("   %-24s %-10s %-10s %s"
                  % (table, "-" if source is None else source,
                     "-" if restored is None else restored, verdict))

        if schema_before == schema_after:
            print("   версия схемы: совпала")
        else:
            problems.append("состав миграций различается")
            print("   версия схемы: РАСХОЖДЕНИЕ")

        if encoding_before == encoding_after:
            print("   кодировка: %s, совпала" % encoding_after)
        else:
            problems.append("кодировка различается: %s и %s" % (encoding_before, encoding_after))

        found = psql(TEMP_CONTAINER, TEMP_DB, arguments.user,
                     "SELECT count(*) FROM backup_check WHERE note = '%s'" % marker)
        if found == "1":
            print("   помеченная строка: на месте, дамп свежий")
        else:
            problems.append("помеченной строки в восстановленной базе нет: дамп не свежий")

        cyrillic = psql(TEMP_CONTAINER, TEMP_DB, arguments.user,
                        "SELECT note FROM backup_check WHERE note = '%s'" % marker)
        if cyrillic == marker:
            print("   кириллица в данных: цела")
        else:
            problems.append("кириллица не выжила восстановление: %r" % cyrillic)

    finally:
        run(["docker", "rm", "-f", TEMP_CONTAINER])
        print("\nчистый экземпляр удалён, рабочая база не затронута")

    print("\n" + "=" * 78)
    if problems:
        print("ПРОТОКОЛ: восстановление не подтверждено")
        for problem in problems:
            print("  -", problem)
        return 1
    print("ПРОТОКОЛ: восстановление подтверждено, данные совпали")
    print("Записи звонков в дамп базы не входят - им нужна отдельная копия.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
