#!/bin/sh
# Резервная копия базы Core. Задача #90.
#
# Пишет дамп в каталог, чистит старые по политике хранения и оставляет рядом
# состояние последнего запуска машинно читаемым файлом. Состояние пишется
# и при успехе, и при ошибке: администратор должен видеть неудачу, а не
# отсутствие файла.
#
# Формат дампа - pg_dump -Fc: сжатый и восстанавливается выборочно. gzip
# сверху не нужен.
#
# Переменные:
#   POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, PGPASSWORD
#   BACKUP_DIR         куда писать, по умолчанию /backups
#   BACKUP_KEEP        сколько копий хранить, по умолчанию 7
#   BACKUP_MAX_MB      предел на каталог, по умолчанию 2048
#
# Секреты только через окружение: в файлы и в репозиторий они не попадают.

set -eu

HOST="${POSTGRES_HOST:-postgres}"
PORT="${POSTGRES_PORT:-5432}"
DB="${POSTGRES_DB:-sirena112}"
USER="${POSTGRES_USER:-sirena112}"
DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP:-7}"
MAX_MB="${BACKUP_MAX_MB:-2048}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="sirena112-${STAMP}.dump"
STATUS="${DIR}/last-backup.json"

mkdir -p "$DIR"
# Дампы содержат учебные данные целиком, поэтому каталог закрыт от чужих.
chmod 700 "$DIR" 2>/dev/null || true

write_status() {
    # $1 - результат, $2 - пояснение, $3 - имя файла или пустое
    #
    # Кавычки и переводы строк из сообщения pg_dump ломают JSON, а файл этот
    # читает администратор машинно. Проверено: без экранирования файл после
    # ошибки не разбирается вообще.
    SAFE="$(printf '%s' "$2" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g')"
    cat > "$STATUS" <<EOF
{
  "result": "$1",
  "message": "$SAFE",
  "file": "$3",
  "finishedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "database": "$DB",
  "keep": $KEEP,
  "note": "Записи звонков сюда не входят: это только база."
}
EOF
    chmod 600 "$STATUS" 2>/dev/null || true
}

fail() {
    echo "backup: ОШИБКА: $1" >&2
    write_status "error" "$1" ""
    exit 1
}

command -v pg_dump >/dev/null 2>&1 || fail "pg_dump не найден"

# Незавершённый дамп не должен выглядеть готовым: пишем в .part и
# переименовываем только после успеха.
PART="${DIR}/${NAME}.part"
if ! pg_dump --format=custom --no-owner --no-privileges \
        --host="$HOST" --port="$PORT" --username="$USER" --dbname="$DB" \
        --file="$PART" 2>/tmp/backup.err; then
    rm -f "$PART"
    fail "$(tr '\n' ' ' < /tmp/backup.err | cut -c1-200)"
fi

mv "$PART" "${DIR}/${NAME}"
chmod 600 "${DIR}/${NAME}" 2>/dev/null || true

# Ротация по количеству.
COUNT="$(ls -1 "$DIR"/sirena112-*.dump 2>/dev/null | wc -l | tr -d ' ')"
if [ "$COUNT" -gt "$KEEP" ]; then
    ls -1t "$DIR"/sirena112-*.dump | tail -n "+$((KEEP + 1))" | while read -r old; do
        echo "backup: удаляю старую копию $(basename "$old")"
        rm -f "$old"
    done
fi

# Ротация по объёму: если каталог всё равно больше предела, снимаем самые
# старые, пока не уложимся. Иначе диск на демо-стенде кончится молча.
while [ "$(du -sm "$DIR" | cut -f1)" -gt "$MAX_MB" ]; do
    OLDEST="$(ls -1t "$DIR"/sirena112-*.dump 2>/dev/null | tail -n 1)"
    [ -n "$OLDEST" ] || break
    echo "backup: каталог больше ${MAX_MB} МБ, удаляю $(basename "$OLDEST")"
    rm -f "$OLDEST"
done

SIZE="$(du -k "${DIR}/${NAME}" | cut -f1)"
echo "backup: готово ${NAME}, ${SIZE} КБ, копий в каталоге $(ls -1 "$DIR"/sirena112-*.dump | wc -l | tr -d ' ')"
write_status "ok" "дамп создан, ${SIZE} КБ" "$NAME"
