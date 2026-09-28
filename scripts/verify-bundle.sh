#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
sha256sum -c SHA256SUMS
echo 'PASS: все файлы offline-bundle соответствуют SHA256SUMS.'
