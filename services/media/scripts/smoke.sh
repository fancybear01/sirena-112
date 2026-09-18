#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MEDIA_BASE_URL:-http://127.0.0.1:8091}"
SIP="${SIP_ADDRESS:-PJSIP/1001}"
SESSION_ID="${SESSION_ID:-smoke-session-1}"
AI_SESSION_ID="${AI_SESSION_ID:-smoke-ai-1}"

echo "== health =="
curl -sf "$BASE_URL/health" | tee /dev/stderr
echo

echo "== ready =="
curl -sf "$BASE_URL/ready" | tee /dev/stderr
echo

echo "== call.start =="
START_JSON=$(curl -sf -X POST "$BASE_URL/internal/v1/calls/start" \
  -H 'Content-Type: application/json' \
  -H "X-Request-Id: smoke-$(date +%s)" \
  -d "{\"sessionId\":\"$SESSION_ID\",\"aiSessionId\":\"$AI_SESSION_ID\",\"sipAddress\":\"$SIP\"}")
echo "$START_JSON"
CALL_ID=$(printf '%s' "$START_JSON" | sed -n 's/.*"callId":"\([^"]*\)".*/\1/p')
if [[ -z "$CALL_ID" ]]; then
  echo "failed to parse callId" >&2
  exit 1
fi

echo "Answer the softphone now, speak, listen for echo. Waiting 25s..."
sleep 25

echo "== call.hangup =="
curl -sf -X POST "$BASE_URL/internal/v1/calls/hangup" \
  -H 'Content-Type: application/json' \
  -d "{\"callId\":\"$CALL_ID\",\"sessionId\":\"$SESSION_ID\"}"
echo
echo "smoke done"
