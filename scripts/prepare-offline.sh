#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OUTPUT="${1:-$ROOT/offline-bundle}"
MODEL_ROOT="$ROOT/models"

# shellcheck disable=SC1091
source "$ROOT/infra/offline/models.env"

download() {
  local url="$1" path="$2" expected="$3" ipv4="${4:-false}"
  if [[ -f "$path" ]] && echo "$expected  $path" | sha256sum -c - >/dev/null 2>&1; then
    return
  fi
  local args=(-fL --retry 3 --output "$path" "$url")
  [[ "$ipv4" == true ]] && args=(-4 "${args[@]}")
  curl "${args[@]}"
  echo "$expected  $path" | sha256sum -c - >/dev/null
}

[[ -f "$ROOT/.env" ]] || bash "$SCRIPT_DIR/stack.sh" init
mkdir -p "$MODEL_ROOT"
download "$VOSK_URL" "$MODEL_ROOT/$VOSK_ARCHIVE" "$VOSK_SHA256" true
if [[ ! -f "$MODEL_ROOT/$VOSK_DIRECTORY/am/final.mdl" ]]; then
  command -v unzip >/dev/null 2>&1 || { echo 'Нужен unzip.' >&2; exit 1; }
  unzip -q -o "$MODEL_ROOT/$VOSK_ARCHIVE" -d "$MODEL_ROOT"
fi
download "$PIPER_MODEL_URL" "$MODEL_ROOT/$PIPER_MODEL" "$PIPER_MODEL_SHA256"
download "$PIPER_CONFIG_URL" "$MODEL_ROOT/$PIPER_CONFIG" "$PIPER_CONFIG_SHA256"

docker info --format '{{.ServerVersion}}' >/dev/null
docker pull 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
docker tag 'postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea' postgres:16-alpine
docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" --profile smoke build --pull
bash "$SCRIPT_DIR/stack.sh" doctor

mkdir -p "$OUTPUT/scripts" "$OUTPUT/docs" "$OUTPUT/infra/offline" "$OUTPUT/models"
rm -f "$OUTPUT/.env" "$OUTPUT/SHA256SUMS"
docker save --output "$OUTPUT/images.tar" \
  postgres:16-alpine \
  sirena-112-ai:2026.09.28 \
  sirena-112-asterisk:2026.09.28 \
  sirena-112-media:2026.09.28 \
  sirena-112-core:2026.09.28 \
  sirena-112-web:2026.09.28 \
  sirena-112-monitor:2026.09.28 \
  sirena-112-smoke:2026.09.28

cp "$ROOT/compose.yaml" "$ROOT/compose.offline.yaml" "$ROOT/.env.example" "$OUTPUT/"
cp "$SCRIPT_DIR/stack.ps1" "$SCRIPT_DIR/stack.sh" "$OUTPUT/scripts/"
cp "$SCRIPT_DIR/verify-bundle.ps1" "$SCRIPT_DIR/verify-bundle.sh" "$OUTPUT/scripts/"
cp "$ROOT/docs/offline-full-stack.md" "$OUTPUT/docs/"
cp "$ROOT/infra/offline/models.env" "$OUTPUT/infra/offline/"
cp -a "$MODEL_ROOT/." "$OUTPUT/models/"
printf '2026.09.28\n' > "$OUTPUT/VERSION"
(
  cd "$OUTPUT"
  find . -type f ! -name SHA256SUMS ! -name .env -print0 |
    sort -z |
    xargs -0 sha256sum |
    sed 's#  \./#  #' > SHA256SUMS
)

echo "PASS: офлайн-пакет подготовлен в $OUTPUT"
echo 'Секретный .env намеренно не включён. На целевой машине выполните ./scripts/stack.sh init.'
