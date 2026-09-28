# Запись учебного голосового звонка

Запись включается только при `MEDIA_MODE=ai`, непустых `MEDIA_RECORDINGS_DIR`,
`CORE_BASE_URL`, `CORE_MEDIA_SERVICE_TOKEN` и `CORE_AUTH_ENABLED=true`. В Compose это частный том
`voice-recordings`: Media пишет, Core монтирует только для чтения. В Core
необходимо включить `CORE_AUTH_ENABLED=true`; без авторизации маршрут
скачивания всегда отвечает 403. Только владелец группы (преподаватель) и
администратор могут получить файл через Core. Сырой WAV не раздаётся Media и
не передаётся в PostgreSQL.

Запись начинается после ответа SIP-клиента и присоединения канала к мосту.
Media пишет отдельный файл для `sessionId/callId`, включая тишину между
репликами, до hangup, обрыва AI или ошибки. Формат: **WAV PCM16 little-endian,
8 kHz, stereo**; левый канал — входящий звук обучающегося, правый — звук AI,
который реально отправлялся обратно по RTP. Обе дорожки синхронизированы по
тикам воспроизведения 20 мс. Стерео нужно для разбора сторон; обычный плеер
воспроизводит оба канала. `durationMs` — длина готового WAV, кратная 20 мс.

Временный файл имеет суффикс `.wav.part`. После успешного завершения и записи
заголовка он атомарно становится `.wav`; при сбое или превышении лимита
удаляется. При старте Media удаляет оставшиеся `.part`. Очередь записи ограничена
100 кадрами; переполнение считается ошибкой записи и не задерживает RTP.
По умолчанию лимит **15 минут** (около 28,8 МБ стерео) и хранение **7 дней**.
Очистка выполняется при старте и раз в час. Значения задаются
`MEDIA_RECORDING_MAX_SECONDS` и `MEDIA_RECORDING_RETENTION_HOURS`. После срока
событие остаётся в истории Core, скачивание возвращает 404.

После финализации Media отправляет `recording.ready` в существующий Core ingest
до `call.ended` с `sessionId`, `callId`, `aiSessionId`, `recordingId=callId`,
`durationMs`, `bytes`, `format=wav`, `sampleRate=8000`, `channels=2` и
относительной ссылкой `/api/teacher/sessions/{sessionId}/recording`. При
неудаче хранилища посылает `media.error`; готовой записи не объявляет. Core
проверяет соответствие `callId` сессии. `GET .../review` возвращает метаданные
готовой записи и только `transcript.final` того же звонка, отсортированные по
`sequence`. Сам текст формирует AI, Media его пересылает. Транскрипт не
заменяет аудиозапись.

В `transcript.final` Media добавляет `recordingStartedAtMs` и
`recordingEndedAtMs` — смещения от начала WAV по своему 20-мс таймеру.
Исходные `startedAtMs/endedAtMs` от AI остаются без изменений: они считают
только переданные AI входные отсчёты и не включают паузы или ответы AI.

## Локальная проверка

```bash
python3 -m venv /tmp/sirena-recording-ai-venv
/tmp/sirena-recording-ai-venv/bin/pip install ./services/ai
cd services/media
go test -race ./...
MEDIA_AI_PYTHON=/tmp/sirena-recording-ai-venv/bin/python go test -race -v ./internal/adapters/asterisk/rtp -run TestActualAIProtocol
cd ../core
./gradlew test --tests '*VoiceRecordingControllerTest' --no-daemon
```

Для softphone-контура включите авторизацию Core по
[`auth-rbac.md`](../../../docs/auth-rbac.md), создайте преподавателя и
учебную VOICE-сессию его группы; запустите AI и Asterisk по инструкции
[AI bridge](ai-websocket.md). В `.env` установите:

```dotenv
CORE_AUTH_ENABLED=true
CORE_MEDIA_SERVICE_TOKEN=<общий секрет не короче 32 символов>
MEDIA_MODE=ai
MEDIA_CORE_BASE_URL=http://core:8080
MEDIA_RECORDINGS_DIR=/recordings
```

Пройдите звонок и завершите его. Затем скачайте и воспроизведите запись с
учётными данными преподавателя (пароль вводится без вывода в терминал):

```bash
python3 services/media/scripts/smoke_recording.py --username teacher \
  --session FIRST_UUID --session SECOND_UUID --play
```

Скрипт проверяет WAV-заголовок, длину, `callId`, порядок транскриптов и запускает
локальный `afplay`, `ffplay` или `aplay`. Два разных `sessionId` нужны потому,
что завершённая бизнес-сессия повторно не запускается. Требования к
персональным данным вынесены в [security task](../../../docs/security-recordings-task.md).
