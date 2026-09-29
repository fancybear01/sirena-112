#!/bin/sh
# Восстановление базы Core из резервной копии. Задача #90.
#
# По умолчанию отказывается писать в базу, которая не помечена как тестовая:
# восстановление поверх рабочей базы стирает данные, и делать это случайно
# нельзя. Чтобы восстановить именно рабочую, нужен явный RESTORE_FORCE=yes.
#
# Переменные:
#   POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, PGPASSWORD
#   RESTORE_DB     куда восстанавливать
#   RESTORE_FORCE  yes - разрешить запись в базу без пометки test/restore
#
# Использование:
#   RESTORE_DB=sirena112_restore sh scripts/restore_postgres.sh /backups/файл.dump

set -eu

DUMP="${1:-}"
HOST="${POSTGRES_HOST:-postgres}"
PORT="${POSTGRES_PORT:-5432}"
USER="${POSTGRES_USER:-sirena112}"
TARGET="${RESTORE_DB:-}"
FORCE="${RESTORE_FORCE:-no}"

[ -n "$DUMP" ] || { echo "restore: укажите файл дампа" >&2; exit 2; }
[ -f "$DUMP" ] || { echo "restore: файла $DUMP нет" >&2; exit 2; }
[ -n "$TARGET" ] || { echo "restore: задайте RESTORE_DB" >&2; exit 2; }

case "$TARGET" in
    *test*|*restore*|*check*) ;;
    *)
        if [ "$FORCE" != "yes" ]; then
            echo "restore: база '$TARGET' не помечена как тестовая." >&2
            echo "restore: восстановление затрёт её данные. Если это осознанно," >&2
            echo "restore: повторите с RESTORE_FORCE=yes." >&2
            exit 3
        fi
        echo "restore: пишу в '$TARGET' по явному RESTORE_FORCE=yes"
        ;;
esac

export PGPASSWORD="${PGPASSWORD:-}"

echo "restore: пересоздаю базу $TARGET"
psql --host="$HOST" --port="$PORT" --username="$USER" --dbname=postgres \
     -v ON_ERROR_STOP=1 -q \
     -c "DROP DATABASE IF EXISTS \"$TARGET\";" \
     -c "CREATE DATABASE \"$TARGET\";"

echo "restore: восстанавливаю из $(basename "$DUMP")"
# --exit-on-error намеренно: частично восстановленная база хуже явной ошибки.
pg_restore --host="$HOST" --port="$PORT" --username="$USER" --dbname="$TARGET" \
           --no-owner --no-privileges --exit-on-error "$DUMP"

echo "restore: готово, база $TARGET восстановлена"
