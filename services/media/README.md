# Media Gateway

Go-сервис телефонно-аудиоконтура Сирена-112.

Скрывает Asterisk (ARI/RTP) от Kotlin Core. В текущем MVP при запуске звонка создаёт bridge и `externalMedia`; после ответа
оператора подключает SIP-канал к bridge. `MEDIA_MODE=echo` возвращает μ-law звук,
`MEDIA_MODE=ai` открывает один AI WebSocket и воспроизводит ответ через RTP.
Подробности и команды проверки: [AI bridge](docs/ai-websocket.md).

Контракт Core↔Media: [`contracts/media-core.md`](../../contracts/media-core.md).

## Архитектура

```text
Core / curl
   │  HTTP commands
   ▼
Go Media ──ARI──► Asterisk ──SIP──► Softphone
   │                  │
   └── RTP echo ◄─────┘ externalMedia
```

Clean Architecture: `domain` ← `application` ← `adapters` / `interfaces`.

## Запуск

Prerequisite: Asterisk из `infra/asterisk` (#9).

```bash
# из корня репозитория
cp -n .env.example .env
docker compose up -d --build asterisk media

curl -sS http://127.0.0.1:8091/health
curl -sS http://127.0.0.1:8091/ready
```

Локально без Docker для Media (Asterisk в compose):

```bash
cd services/media
export $(grep -v '^#' .env.example | xargs)
export ARI_BASE_URL=http://127.0.0.1:8088/ari
export RTP_PUBLIC_HOST=host.docker.internal
go run ./cmd/media
```

## Environment

См. [`.env.example`](.env.example).

| Variable | Meaning |
|----------|---------|
| `MEDIA_HTTP_ADDR` | listen addr (`:8091`) |
| `ARI_BASE_URL` | e.g. `http://asterisk:8088/ari` |
| `ARI_USERNAME` / `ARI_PASSWORD` | ARI user (not SIP 1001) |
| `ARI_APP` | Stasis app name (`sirena-media`) |
| `RTP_LISTEN_ADDR` / `RTP_PORT` / `RTP_PORT_END` | UDP host and inclusive port range for externalMedia |
| `MEDIA_MAX_CALLS` | Maximum admitted calls, including starts and calls awaiting cleanup; default is 32 or the RTP port range size, whichever is smaller |
| `RTP_PUBLIC_HOST` | host Asterisk dials for RTP (`media` in compose) |
| `MEDIA_MODE` | `echo` (default) / `ai` |
| `AI_BASE_URL` | WS base URL, e.g. `ws://127.0.0.1:8090` |
| `CORE_BASE_URL` | HTTP base URL Core; empty = logging publisher |
| `LOG_LEVEL` | `debug` / `info` / … |

Секреты не логируются.

## API (кратко)

```bash
# start
curl -sS -X POST http://127.0.0.1:8091/internal/v1/calls/start \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"s1","aiSessionId":"ai1","sipAddress":"PJSIP/1001"}'

# hangup
curl -sS -X POST http://127.0.0.1:8091/internal/v1/calls/hangup \
  -H 'Content-Type: application/json' \
  -d '{"callId":"<id>","sessionId":"s1"}'
```

`speech.play` → `501`. `speech.cancel` с `callId` отправляет `response.cancel`
и очищает очередь воспроизведения. `POST /internal/v1/calls/{callId}/input/flush`
завершает входную реплику явно. В echo обе AI-команды возвращают `501`.

С непустым `CORE_BASE_URL` события lifecycle, `transcript.final` и `media.error`
уходят в `/internal/v1/media/events`. Без него используется logging publisher.

Запись учебных AI-звонков включается отдельно через `MEDIA_RECORDINGS_DIR` и
авторизованный Core. Формат WAV stereo, защищённое скачивание и smoke описаны
в [docs/recording.md](docs/recording.md).

## RTP

| | |
|--|--|
| Codec | μ-law (PCMU), PT=0 |
| Rate | 8 kHz mono |
| Packet | 20 ms |
| Demo | echo |

В логах после hangup: `rxPackets` / `txPackets` / `lostPackets` **без** audio payload.

## Local SIP test

1. Softphone: user `1001`, password из `.env`, server `127.0.0.1:5060`.
2. `docker compose up -d --build asterisk media`
3. `curl /ready`
4. `POST /internal/v1/calls/start` на `PJSIP/1001`
5. Ответить, сказать фразу → слышен echo
6. `POST /internal/v1/calls/hangup`
7. Повторить smoke: `./scripts/smoke.sh`

## Troubleshooting

| Симптом | Что проверить |
|---------|----------------|
| `/ready` 503 | `docker compose ps asterisk`, ARI user/password |
| Нет входящего на softphone | регистрация 1001, `pjsip show endpoints` |
| Нет echo | `RTP_PUBLIC_HOST`, логи `rtp echo stopped`, firewall UDP |
| SIP 1001 на ARI 401 | ARI логин = `media`, не `1001` |

## Tests

```bash
cd services/media
go test -race ./...
go vet ./...
go build ./cmd/media
```

## Жизненный цикл и диагностика

- `/ready` требует доступного ARI HTTP и подключённого WebSocket событий.
  Пока WebSocket не подключён, `call.start` возвращает `503`.
- `call.answered` публикуется только после подключения SIP-канала к bridge.
  Ранние события во время запуска сохраняются до завершения инициализации.
- Обрыв ARI WebSocket завершает текущий звонок с `FAILED` и запускает очистку:
  события, пропущенные при переподключении, нельзя безопасно восстановить.
- Отмена start откатывает созданные ресурсы независимо от контекста HTTP-запроса.
  SIGINT/SIGTERM закрывает HTTP и освобождает активный звонок.
- Если cleanup завершился ошибкой, hangup возвращает ошибку; ID ресурсов
  остаются в памяти. Фоновая задача повторяет cleanup каждые 5 секунд;
  повторный hangup тоже запускает очистку. Это относится и к rollback start.
  RTP-порт остаётся зарезервированным до успешного cleanup в Asterisk.
- RTP parser учитывает CSRC, extension и padding. Дубли и опоздавшие пакеты
  отбрасываются; `lostPackets` считает обнаруженные пропуски последовательности,
  без вычитания позднее пришедших пакетов. Смена SSRC сбрасывает последовательность.
  PCMU timestamp растёт на фактическое число аудиосэмплов в пакете.

Регрессионные тесты используют локальные HTTP/WebSocket ARI mocks и UDP.
Они не заменяют smoke со звонком через настоящий Asterisk и softphone.

## Несколько звонков и восстановление

В Compose задан диапазон `18000–18099`: каждый звонок получает отдельный
UDP-порт. Если `RTP_PORT_END` не задан, диапазон состоит только из `RTP_PORT`
для совместимости со старой конфигурацией. Занятые другим процессом порты
пропускаются. Когда свободных портов нет, start возвращает
`503 capacity_exhausted`.

События обрабатываются последовательно для каждого звонка в отдельной очереди
(до 64 событий). Медленный ARI-запрос не блокирует общий реестр и WebSocket
reader. Переполнение очереди завершает звонок с ошибкой, поскольку потеря
событий могла бы оставить неверное состояние.

При неудачном rollback сохраняется резерв sessionId: повторный start этой
сессии получает `409` до завершения cleanup. При необходимости можно явно
повторить hangup по `sessionId`, даже если start не вернул callId.

Очередь очистки хранится только в памяти. После аварийного завершения процесса
или `SIGKILL` автоматическое восстановление оставшихся ARI-ресурсов пока не
реализовано. Штатная остановка освобождает звонки параллельно.

Подключение AI описано в [AI WebSocket](docs/ai-websocket.md).
