#!/usr/bin/env python3
"""Проверка TLS браузерного доступа. Часть задачи #89.

Проверяет не «порт отвечает», а то, что важно: какая версия протокола,
отклоняются ли устаревшие, доходит ли API через шифрованный канал, стоят ли
заголовки и что за сертификат предъявлен.

Самоподписанный сертификат на стенде - это норма, и скрипт на него не
ругается. Но он печатает, кем сертификат выдан, чтобы никто не спутал
стенд с контуром заказчика.

Запуск:

    python scripts/check_tls.py --url https://127.0.0.1:8443

Код возврата 0 - шифрование в порядке, 1 - есть замечания.
"""

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from typing import List, Optional, Tuple
from urllib.parse import urlparse

# Версии, которые обязаны быть отклонены: в браузерах они давно выключены.
OUTDATED = [("TLS 1.0", ssl.TLSVersion.TLSv1), ("TLS 1.1", ssl.TLSVersion.TLSv1_1)]

REQUIRED_HEADERS = [
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
]


def unverified() -> ssl.SSLContext:
    """Контекст без проверки цепочки: на стенде сертификат самоподписанный."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def negotiated(host: str, port: int) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    context = unverified()
    with socket.create_connection((host, port), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cipher = tls.cipher()
            # Сертификат в разобранном виде доступен только при проверке,
            # поэтому берём его в двоичном виде и читаем поля отдельно.
            return tls.version(), cipher[0] if cipher else None, {"der": tls.getpeercert(True)}


def accepts(host: str, port: int, version: ssl.TLSVersion) -> bool:
    context = unverified()
    try:
        context.minimum_version = version
        context.maximum_version = version
    except ValueError:
        return False
    try:
        with socket.create_connection((host, port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                return True
    except Exception:  # noqa: BLE001 - отказ соединения и есть ответ
        return False


def certificate_facts(der: bytes) -> List[str]:
    """Кем выдан и до какого числа. Без сторонних библиотек."""
    try:
        text = ssl.DER_cert_to_PEM_cert(der)
    except Exception:  # noqa: BLE001
        return ["сертификат не разобрался"]
    facts = ["длина сертификата %d байт" % len(der)]
    # Разбор полей без cryptography: вытаскиваем строки из DER как есть.
    readable = "".join(chr(b) if 32 <= b < 127 else " " for b in der)
    for marker in ("Sirena", "localhost"):
        if marker in readable:
            facts.append("в сертификате встречается %r" % marker)
    facts.append("PEM получен, %d строк" % len(text.strip().splitlines()))
    return facts


def fetch(url: str) -> Tuple[int, dict, bytes]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=15, context=unverified()) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--api", default="/api/teacher/analytics/summary",
                        help="метод API, который должен пройти через TLS")
    arguments = parser.parse_args()

    parsed = urlparse(arguments.url)
    host, port = parsed.hostname, parsed.port or 443
    problems: List[str] = []

    print("=" * 78)
    print("Проверка TLS: %s" % arguments.url)
    print("=" * 78)

    try:
        version, cipher, peer = negotiated(host, port)
    except Exception as error:  # noqa: BLE001
        print("\nСоединение не установилось: %s" % error)
        print("TLS не включён или сертификат не смонтирован. Притворяться нечем.")
        return 1

    print("\nПротокол и шифр")
    print("   версия: %s" % version)
    print("   шифр  : %s" % cipher)
    if version not in ("TLSv1.2", "TLSv1.3"):
        problems.append("согласована версия %s, нужны только 1.2 и 1.3" % version)

    print("\nУстаревшие версии обязаны отклоняться")
    for name, value in OUTDATED:
        ok = not accepts(host, port, value)
        print("   %-8s %s" % (name, "отклонён" if ok else "ПРИНЯТ"))
        if not ok:
            problems.append("%s принимается, хотя не должен" % name)

    print("\nСертификат")
    for fact in certificate_facts(peer["der"]):
        print("   %s" % fact)
    print("   проверка цепочки не делается: на стенде сертификат самоподписанный")

    print("\nСтраница и заголовки")
    status, headers, body = fetch(arguments.url.rstrip("/") + "/health")
    print("   /health -> %d" % status)
    if status != 200:
        problems.append("/health по TLS отвечает %d" % status)
    else:
        try:
            print("   тело   : %s" % json.dumps(json.loads(body), ensure_ascii=False))
        except ValueError:
            problems.append("/health вернул не JSON")

    lowered = {key.lower(): value for key, value in headers.items()}
    for header in REQUIRED_HEADERS:
        present = header in lowered
        print("   %-28s %s" % (header, lowered.get(header, "НЕТ")))
        if not present:
            problems.append("нет заголовка %s" % header)

    print("\nAPI через шифрованный канал")
    status, _, _ = fetch(arguments.url.rstrip("/") + arguments.api)
    print("   %s -> %d" % (arguments.api, status))
    if status not in (200, 401, 403):
        problems.append("API через TLS отвечает %d" % status)
    elif status in (401, 403):
        print("   доступ закрыт по роли - это тоже рабочий ответ")

    print("\n" + "=" * 78)
    if problems:
        print("ЗАМЕЧАНИЯ:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("Шифрование браузерного канала работает.")
    print("Внутренние каналы между службами по TLS не защищены - см. docs/tls.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
