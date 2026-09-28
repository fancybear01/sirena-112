#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
BUNDLE_PATH="${2:-}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE_ENV="$ROOT/.env.example"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/compose.yaml" -f "$ROOT/compose.offline.yaml")

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

random_secret() {
  local bytes="${1:-24}"
  head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
}

init_env() {
  if [[ -f "$ENV_FILE" ]]; then
    echo '.env уже существует; существующие секреты не изменены.'
    return
  fi
  cp "$EXAMPLE_ENV" "$ENV_FILE"
  sed -i \
    -e "s/GENERATE_POSTGRES_PASSWORD/$(random_secret 24)/" \
    -e "s/GENERATE_ADMIN_PASSWORD/$(random_secret 18)/" \
    -e "s/GENERATE_CORE_MEDIA_TOKEN/$(random_secret 32)/" \
    -e "s/GENERATE_AI_SERVICE_TOKEN/$(random_secret 32)/" \
    -e "s/GENERATE_SIP_1001_PASSWORD/$(random_secret 18)/" \
    -e "s/GENERATE_SIP_1002_PASSWORD/$(random_secret 18)/" \
    -e "s/GENERATE_ARI_PASSWORD/$(random_secret 24)/" \
    "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo 'Создан .env с локальными случайными секретами. Файл исключён из Git.'
}

load_env() {
  [[ -f "$ENV_FILE" ]] || fail 'Файл .env отсутствует. Выполните: ./scripts/stack.sh init'
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

assert_secret() {
  local name="$1" minimum="$2" value="${!1:-}"
  [[ ${#value} -ge $minimum ]] || fail "$name слишком короткий или отсутствует"
  [[ ! "$value" =~ ^(GENERATE_|change-me|sirena112-local) ]] || fail "$name содержит placeholder"
}

assert_models() {
  [[ -f "$ROOT/models/vosk-model-small-ru-0.22/am/final.mdl" ]] || fail 'Отсутствует Vosk. Выполните prepare-offline.sh.'
  [[ -f "$ROOT/models/ru_RU-dmitri-medium.onnx" ]] || fail 'Отсутствует Piper ONNX.'
  [[ -f "$ROOT/models/ru_RU-dmitri-medium.onnx.json" ]] || fail 'Отсутствует Piper JSON.'
  echo '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4  models/vosk-model-small-ru-0.22.zip' | (cd "$ROOT" && sha256sum -c -) >/dev/null
  echo 'f073356ebc4bd0f80c5af58df2953a5988bd5bdab1eb38635ce960b071fbefcb  models/ru_RU-dmitri-medium.onnx' | (cd "$ROOT" && sha256sum -c -) >/dev/null
  echo '667ef3117bc642c2892dff7690d8bdc8ca4228aeaa783b2dc1416df632855e0d  models/ru_RU-dmitri-medium.onnx.json' | (cd "$ROOT" && sha256sum -c -) >/dev/null
}

assert_images() {
  local images=(
    postgres:16-alpine
    sirena-112-ai:2026.09.28
    sirena-112-asterisk:2026.09.28
    sirena-112-media:2026.09.28
    sirena-112-core:2026.09.28
    sirena-112-web:2026.09.28
    sirena-112-monitor:2026.09.28
    sirena-112-smoke:2026.09.28
  )
  local image
  for image in "${images[@]}"; do
    docker image inspect "$image" >/dev/null 2>&1 || fail "Docker-образ $image отсутствует"
  done
}

assert_ports() {
  if [[ -n "$("${COMPOSE[@]}" ps --status running -q 2>/dev/null || true)" ]]; then
    return
  fi
  command -v ss >/dev/null 2>&1 || return
  local ports=("$POSTGRES_PORT" "$WEB_PORT" "$CORE_PORT" "$AI_PORT" "$MEDIA_PORT" "$ASTERISK_HTTP_PORT" "$ASTERISK_SIP_PORT" "$MONITOR_PORT")
  local port
  for port in "${ports[@]}"; do
    if ss -ltn "sport = :$port" | tail -n +2 | grep -q .; then
      fail "TCP-порт $port уже занят"
    fi
  done
}

doctor() {
  docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || fail 'Docker Engine недоступен'
  load_env
  assert_secret POSTGRES_PASSWORD 16
  assert_secret CORE_MEDIA_SERVICE_TOKEN 32
  assert_secret AI_SERVICE_TOKEN 32
  assert_secret ASTERISK_ARI_PASSWORD 16
  assert_secret ASTERISK_SIP_1001_PASSWORD 12
  assert_secret ASTERISK_SIP_1002_PASSWORD 12
  [[ "$SIRENA_BIND_ADDRESS" == '127.0.0.1' ]] || fail 'Автономный профиль разрешает только SIRENA_BIND_ADDRESS=127.0.0.1. Для LAN нужен отдельный TLS/auth профиль и новая сборка.'
  assert_models
  assert_images
  "${COMPOSE[@]}" config --quiet
  assert_ports
  echo 'PASS: Docker, Compose, секреты, модели, образы, конфигурация и порты готовы.'
}

case "$ACTION" in
  init)
    init_env
    ;;
  doctor)
    doctor
    ;;
  start)
    doctor
    "${COMPOSE[@]}" up --detach --wait --wait-timeout 300 --no-build --pull never
    echo 'Стенд готов: Web http://localhost:5173, мониторинг http://localhost:8099/status'
    ;;
  stop)
    load_env
    "${COMPOSE[@]}" down
    echo 'Контейнеры остановлены; том PostgreSQL сохранён.'
    ;;
  restart)
    load_env
    "${COMPOSE[@]}" restart
    "${COMPOSE[@]}" up --detach --wait --wait-timeout 300 --no-build --pull never
    ;;
  status)
    load_env
    "${COMPOSE[@]}" ps
    curl -fsS http://127.0.0.1:8099/status || true
    echo
    ;;
  smoke)
    load_env
    "${COMPOSE[@]}" --profile smoke run --no-deps --rm card-smoke
    "${COMPOSE[@]}" --profile smoke run --no-deps --rm voice-smoke
    ;;
  logs)
    load_env
    "${COMPOSE[@]}" logs --no-color --tail 200
    ;;
  update)
    load_env
    [[ -n "$BUNDLE_PATH" ]] || BUNDLE_PATH="$ROOT/offline-bundle/images.tar"
    [[ -f "$BUNDLE_PATH" ]] || fail "Не найден $BUNDLE_PATH"
    docker load --input "$BUNDLE_PATH"
    doctor
    "${COMPOSE[@]}" up --detach --wait --wait-timeout 300 --no-build --pull never --force-recreate
    echo 'Образы обновлены; данные PostgreSQL сохранены.'
    ;;
  *)
    fail 'Действия: init, doctor, start, stop, restart, status, smoke, logs, update'
    ;;
esac
