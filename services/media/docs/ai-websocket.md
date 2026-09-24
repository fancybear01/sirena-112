# Рабочий мост Media ↔ AI

Media поддерживает `MEDIA_MODE=echo|ai` (по умолчанию `echo`). Echo не требует
AI и сохраняет существующий `scripts/smoke.sh`. Автоматического переключения
живого AI-звонка в echo нет: ошибка AI завершает звонок с диагностикой в Core.

## Поток звонка

1. Core создаёт голосовую AI-сессию и передаёт `sessionId`, `aiSessionId`,
   `sipAddress` в Media. Для полного сценария используйте Core API, а не
   выдуманные идентификаторы из standalone echo smoke.
2. После ответа SIP-канала и подключения bridge Media открывает один
   `{AI_BASE_URL}/internal/v1/voice/{aiSessionId}?sessionId=...`.
3. До аудио отправляется один JSON `stream.start` (PCM16 LE, mono, 16000 Hz,
   20 ms). Контекст принадлежит звонку, не HTTP-запросу start.
4. RTP PCMU 8 кГц проходит декодирование и потоковый FIR-ресемплер до 16 кГц.
   Границы RTP сохраняются в непрерывном sample stream; на WS уходят блоки
   ровно по 640 байт. FIR хранит историю между пакетами.
5. `POST /internal/v1/calls/{callId}/input/flush` явно завершает реплику.
   Неполный входной PCM-кадр дополняется нулями. Пустой flush отклоняется.
6. AI молчит на отдельные входные кадры. После flush reader принимает
   `transcript.final`, `response.started` (JSON, не звук), binary PCM,
   `response.completed`, `caller.state_changed`. JSON никогда не попадает в
   аудиоконвертер. `simulated` и временные границы транскрипта сохраняются.
7. PCM-ответ фильтруется перед децимацией до 8 кГц и кодируется в μ-law.
   Пакеты по 160 байт отправляются раз в 20 мс. Sequence растёт по отправленным
   пакетам, timestamp — по 8-кГц sample clock, SSRC постоянен в пределах звонка.
   Последний неполный выходной пакет дополняется μ-law тишиной.

Ресемплер: 63-tap windowed-sinc FIR, cutoff 3.4 кГц при 16 кГц, задержка
31 отсчёт на направление. Тесты проверяют непрерывность, тишину, искажения
кругового преобразования и подавление 6-кГц компоненты перед downsampling.
Это узкополосный телефонный канал: исходных частот выше 4 кГц в PCMU нет.

## Границы реплик и отмена

Текущий режим использует **явный flush**, без VAD. Завершайте фрагмент раньше
лимита AI в 30 секунд. Пока AI отвечает и очередь проигрывается, входящие RTP
дренируются и отбрасываются: следующий ход не смешивается с текущим ответом.
Автоматическое определение перебивания не реализовано.

`POST /internal/v1/speech/cancel` с `{"callId":"..."}` отправляет
`response.cancel`, сбрасывает недоигранный PCM и ждёт
`response.completed` с `cancelled:true`. До подтверждения оставшийся звук
старого ответа игнорируется. После подтверждения можно записывать новый ход.

## Очереди, ошибки, завершение

- Handshake и каждая запись WS ограничены 3 секундами.
- У WS один writer и один reader; очередь записи — 64 сообщения.
- Очередь RTP playback — 500 кадров / 10 секунд. Переполнение любой аудиоочереди
  становится ошибкой, а не бесконечным накоплением задержки.
- Reader обрабатывает большой PCM блок небольшими порциями, не удерживая
  блокировку UDP на всём ответе. ARI использует отдельные очереди звонков.
- Ping/pong и read deadline 60 секунд обнаруживают потерянное соединение.
- На hangup/disconnect выполняется best-effort `stream.stop` (не более 300 мс),
  затем закрываются WS и UDP, завершаются reader/writer/playback и удаляются
  SIP channel, externalMedia и bridge. Неудачный ARI cleanup повторяется фоном.
- AI `error` обрабатывается как ошибка текущего звонка. В частности,
  `speech.unavailable` означает отсутствие моделей, а не реальное распознавание.
  Для проверки без моделей запускайте scripted/silence сервер ниже.
- При `caller.state_changed` с `hangUp:true` сначала доигрывается очередь
  ответа, затем завершается звонок. SIP hangup прекращает звук сразу.

## Доставка событий в Core

`CORE_BASE_URL=http://...:8080` включает HTTP publisher на существующий
`POST /internal/v1/media/events`. Пустая настройка оставляет logging publisher
для независимого echo smoke. В Compose настройка называется `MEDIA_CORE_BASE_URL`.

Публикуются `call.ringing`, `call.answered`, `call.ended`, `transcript.final`,
`media.error`. Envelope сохраняет `eventId`, `sessionId`, `timestamp`,
`source=media`; payload содержит `callId` и `aiSessionId`. PCM не публикуется
и не логируется, доступа к PostgreSQL из Media нет.

Publisher имеет очередь 256 событий, timeout HTTP 2 секунды и до трёх попыток
для сетевых/5xx/429/409 ошибок. Повтор отправляет те же сериализованные байты,
включая eventId. Core дедуплицирует и не откатывает терминальную сессию из-за
поздних lifecycle-событий. При исчерпании повторов или очереди ошибка логируется;
постоянного outbox нет, поэтому гарантий доставки через рестарт Media нет.

## Автоматические проверки

Из корня:

```bash
cd services/media
go test -race ./...
go vet ./...
go build ./cmd/media
```

`tests/voicefixture` теперь использует рабочий WS-клиент: два хода без ответов
на отдельные входные кадры, текстовые события до/после PCM, `stream.stop`.
Тесты ARI/RTP дополнительно проверяют pacing, переполнение, disconnect, cleanup
всех ARI-ресурсов и повторный звонок на том же порту.

Проверка **текущего Python AI**, без моделей, Docker и softphone:

```bash
# из корня
python3 -m venv /tmp/sirena-ai-test-env
/tmp/sirena-ai-test-env/bin/pip install ./services/ai
cd services/media
MEDIA_AI_PYTHON=/tmp/sirena-ai-test-env/bin/python \
  go test -race -v ./internal/adapters/asterisk/rtp -run TestActualAIProtocol -count=1
```

Тест запускает настоящий AI app с его `ScriptedRecognizer` и
`SilenceSynthesizer`. Проверяются два хода, два последовательных звонка,
`simulated:true`, корреляция и равномерный RTP. Ответом должна быть тишина.
Это также отдельный шаг существующего CI `media / test-build`.

С установленными Vosk/Piper и настроенными `AI_STT`, `AI_STT_MODEL`, `AI_TTS`,
`AI_TTS_MODEL` добавьте `MEDIA_AI_REAL=1` к той же команде. Тогда тест берёт
операторские WAV из AI fixtures и требует `simulated:false`. Настройка моделей:
[`docs/voice-readiness.md`](../../../docs/voice-readiness.md).

## Softphone smoke с событиями Core

1. Поднимите AI (с моделями либо тестовый сервер):

   ```bash
   /tmp/sirena-ai-test-env/bin/python services/media/scripts/ai-test-server.py --port 8090
   ```

   Сервер слушает loopback. Если AI на Mac, а Core/Media внутри Docker,
   запустите AI на доступном контейнерам адресе (см. флаг `--host` скрипта).

2. В `.env` задайте:

   ```dotenv
   MEDIA_MODE=ai
   MEDIA_AI_BASE_URL=ws://host.docker.internal:8090
   MEDIA_CORE_BASE_URL=http://core:8080
   CORE_AI_BASE_URL=http://host.docker.internal:8090
   CORE_MEDIA_MODE=http
   ```

3. `docker compose up -d --build postgres core asterisk media`.
   Зарегистрируйте softphone 1001 по инструкции Asterisk. Создайте через Core/UI
   две разные READY VOICE-сессии: завершённую бизнес-сессию повторно не запускают.
4. Запустите:

   ```bash
   python3 services/media/scripts/smoke_ai.py --session FIRST_UUID --session SECOND_UUID
   ```

   Ответьте на звонок и говорите по подсказкам. Скрипт явно делает два flush,
   проверяет транскрипты и lifecycle в Core, затем повторяет звонок для второй
   сессии без рестарта Media. В scripted режиме звук — тишина; с моделями — речь.
5. После отбоя проверьте `docker compose exec asterisk asterisk -rx "core show channels"`
   и `docker compose exec asterisk asterisk -rx "bridge show all"`.

Для проверки disconnect во время звонка остановите AI: Core должен получить
`media.error`, ARI-ресурсы должны исчезнуть. После возврата AI создайте новую
VOICE-сессию и повторите smoke. Для диагностического возврата к echo установите
`MEDIA_MODE=echo`, очистите `MEDIA_CORE_BASE_URL` и пересоздайте Media, затем
выполните прежний `bash services/media/scripts/smoke.sh`.

Результаты локальной проверки: [validation](ai-validation.md).
PR не создан: по указанию владельца изменения остаются локально.
