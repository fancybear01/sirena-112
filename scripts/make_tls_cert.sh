#!/bin/sh
# Сертификат для локального TLS. Задача #89.
#
# Выпускает самоподписанный сертификат для стенда. Для контура заказчика
# сюда кладётся сертификат их удостоверяющего центра теми же именами -
# ничего в конфигурации менять не нужно.
#
# Ключ и сертификат в репозиторий не попадают: каталог certs в .gitignore.
#
# Использование:
#   sh scripts/make_tls_cert.sh
#   TLS_DAYS=90 TLS_HOST=sirena.local sh scripts/make_tls_cert.sh

set -eu

DIR="${TLS_DIR:-certs}"
HOST="${TLS_HOST:-localhost}"
DAYS="${TLS_DAYS:-397}"

command -v openssl >/dev/null 2>&1 || {
    echo "нужен openssl" >&2
    exit 1
}

mkdir -p "$DIR"
chmod 700 "$DIR"

KEY="${DIR}/sirena.key"
CRT="${DIR}/sirena.crt"

if [ -f "$CRT" ] && [ "${TLS_FORCE:-no}" != "yes" ]; then
    echo "Сертификат уже есть: $CRT"
    openssl x509 -in "$CRT" -noout -subject -enddate
    echo "Перевыпустить: TLS_FORCE=yes sh scripts/make_tls_cert.sh"
    exit 0
fi

# SAN обязателен: браузеры давно не смотрят на CN, и без SAN сертификат
# будет отклонён даже как самоподписанный.
openssl req -x509 -newkey rsa:2048 -sha256 -nodes \
    -keyout "$KEY" -out "$CRT" -days "$DAYS" \
    -subj "/CN=${HOST}/O=Sirena-112 local stand" \
    -addext "subjectAltName=DNS:${HOST},DNS:localhost,IP:127.0.0.1" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

chmod 600 "$KEY"
chmod 644 "$CRT"

echo "Выпущен сертификат на ${DAYS} дней:"
openssl x509 -in "$CRT" -noout -subject -enddate -ext subjectAltName | sed 's/^/  /'
echo
echo "Ключ:        $KEY (права 600)"
echo "Сертификат:  $CRT"
echo
echo "Самоподписанный сертификат браузер пометит как недоверенный - это"
echo "ожидаемо для стенда. В контуре заказчика положите сюда их сертификат"
echo "теми же именами."
echo
echo "Смена: перевыпустить с TLS_FORCE=yes и перезапустить web."
echo "Срок ${DAYS} дней выбран не случайно: браузеры не принимают серверные"
echo "сертификаты со сроком больше 398 дней."
