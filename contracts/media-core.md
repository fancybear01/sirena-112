# Контракт Core ↔ Media

Версия MVP для задач #10–#12. AI voice stream описан в `media-ai.md` и в этом
срезе **не реализуется** (вместо него RTP echo).

## Роли

| Компонент | Ответственность |
|-----------|-----------------|
| Kotlin Core | бизнес-сессия, создаёт `aiSessionId`, шлёт команды Media |
| Go Media | ARI/SIP/RTP, technical call state, публикация media-событий |
| Asterisk | телефония |
| Python AI | STT/TTS/диалог (после MVP) |

Media **не** ходит в PostgreSQL и не считает score.

## Transport

- Core → Media: HTTP JSON, base URL `CORE_MEDIA_BASE_URL` (по умолчанию `http://127.0.0.1:8091`)
- Media → Core: port `CoreEventPublisher`; в MVP — structured log stub. Реальный HTTP ingest подключается, когда Core его отдаст.
- Correlation: заголовок `X-Request-Id` (опционально) + `sessionId` / `callId` в теле и событиях.

## Команды Core → Media

### `call.start`

`POST /internal/v1/calls/start`

```json
{
  "sessionId": "0199d7b6-0000-7000-8000-000000000002",
  "aiSessionId": "ai-0199d7b6",
  "sipAddress": "PJSIP/1001"
}
```

Ответ `202 Accepted`:

```json
{
  "callId": "...",
  "sessionId": "...",
  "aiSessionId": "...",
  "sipAddress": "PJSIP/1001",
  "state": "RINGING",
  "channelId": "...",
  "bridgeId": "..."
}
```

`aiSessionId` создаёт Core (через AI) **до** `call.start` и передаёт в Media.
`sipAddress` может быть `PJSIP/1001` или коротким `1001`.

Идемпотентность: повторный start для активной `sessionId` → `409 conflict`.

### `call.hangup`

`POST /internal/v1/calls/hangup`

```json
{
  "callId": "...",
  "sessionId": "..."
}
```

Достаточно одного из идентификаторов; пустой запрос → `400`. Если переданы оба,
они должны соответствовать одному звонку. Повторный успешный hangup идемпотентен
→ `200` со `state: ENDED`. При ошибке очистки возвращается ошибка, ID ресурсов
сохраняются для повторного hangup и фонового повтора cleanup каждые 5 секунд.
Неудачный rollback start обрабатывается так же; до завершения cleanup
сессия остаётся занятой (`409` на повторный start).

### `speech.play` / `speech.cancel`

`POST /internal/v1/speech/play`  
`POST /internal/v1/speech/cancel`

MVP stub → `501 not_implemented` (до AI stream).

### Health

- `GET /health` → процесс жив
- `GET /ready` → доступны ARI HTTP и WebSocket событий (`503` если нет)
- `GET /internal/v1/calls/{callId}` → debug snapshot

## События Media → Core

Конверт как в `events.md`:

```json
{
  "eventId": "...",
  "sessionId": "...",
  "type": "call.answered",
  "timestamp": "2026-09-15T12:00:05.420Z",
  "source": "media",
  "payload": {
    "callId": "...",
    "aiSessionId": "...",
    "channelId": "..."
  }
}
```

| type | Когда |
|------|--------|
| `call.ringing` | исходящий dial / Ring |
| `call.answered` | канал Up + bridge |
| `call.ended` | hangup / ChannelDestroyed / потеря ARI WebSocket или externalMedia после cleanup |
| `media.error` | сбой ARI/start |
| `media.latency` | зарезервировано (опционально) |
| `system.error` | зарезервировано |

Идемпотентность на стороне Core — по `eventId`.

## Technical call states (Media)

`NEW → RINGING → ACTIVE → ENDING → ENDED` (+ `FAILED`)

Это не копия Core session FSM.

## RTP MVP

| Параметр | Значение |
|----------|----------|
| Codec | G.711 μ-law (`ulaw`) |
| Clock | 8 kHz mono |
| Payload type | 0 |
| Frame | 20 ms (160 samples) |
| Mode | echo (до AI) |
| Path | SIP ↔ Asterisk bridge ↔ externalMedia ↔ RTP ↔ Go |

`RTP_PUBLIC_HOST`: в compose = `media`; при Media на хосте = `host.docker.internal`.

## Ошибки HTTP

| Code | error | Смысл |
|------|-------|--------|
| 400 | invalid_argument | нет обязательных полей |
| 404 | not_found | неизвестный callId |
| 409 | conflict | активный звонок на sessionId |
| 501 | not_implemented | speech stubs |
| 503 | ari_unavailable | /ready или ARI down |
| 503 | capacity_exhausted | все RTP-порты заняты или ожидают cleanup |
| 500 | internal_error | прочее |

## Smoke sequence

1. `docker compose up -d --build asterisk media`
2. Softphone регистрирует `1001`
3. `curl /ready`
4. `curl POST /internal/v1/calls/start` → ответ / ringing
5. Ответить на звонок → слышен echo
6. `curl POST /internal/v1/calls/hangup`
7. Проверить в логах cleanup / RTP stats без payload аудио

Скрипт: `services/media/scripts/smoke.sh`.

## Явные ограничения MVP

- нет AI WebSocket (контракт уже в `media-ai.md`);
- число одновременных звонков ограничено диапазоном `RTP_PORT`–`RTP_PORT_END`;
- Core event publisher = log stub;
- нет SRTP/Opus;
- ARI HTTP на хосте только `127.0.0.1`.
