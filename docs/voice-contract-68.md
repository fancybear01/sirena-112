# Проверка стыка Core–AI–Media (#68)

## Автоматический контрактный прогон

Из `services/core`:

```powershell
.\gradlew.bat test --no-daemon --tests '*VoiceCrossServiceContractTest' --tests '*VoiceTrainingIntegrationTest' --tests '*HttpMediaClientTest' --tests '*SessionEventReplayTest'
```

`VoiceCrossServiceContractTest` поднимает настоящий Spring Core с его HTTP
адаптерами. Внешние HTTP ответы AI и Media фиксируются тестовым сервером по
фактическим JSON-контрактам. Тест создаёт VOICE-сессию в Core и проверяет:

- `POST /ai/voice/sessions` получает тот же `sessionId` и `scenario.id`, что
  созданы Core; выданный `aiSessionId` без подмены уходит в
  `POST /internal/v1/calls/start` вместе с `sessionId` и SIP-адресом;
- Media `202` содержит те же ID и `callId`; `409`/`503` дают понятный статус
  клиенту, освобождают отклонённую AI-сессию и оставляют учебную сессию в READY;
- таймаут даёт `503` с предупреждением проверить состояние звонка перед
  повтором: Media могла принять команду до разрыва связи;
- `call.ringing → call.answered → transcript.final → call.ended` проходит
  через `POST /internal/v1/media/events`, повтор того же `eventId` возвращает
  `accepted=false`, повтор с изменённым payload отклоняется `409`;
- `GET /api/teacher/sessions/{sessionId}/events` и
  `/ws/sessions/{sessionId}/events` возвращают одни и те же eventId без дублей;
  повторный hangup не создаёт вторую команду Media;
- после отказа Media карточная сессия по-прежнему запускается.

В XML-отчёте Gradle есть строка вида
`voice-contract sessionId=<UUID> aiSessionId=voice-<UUID> callId=call-<UUID> events=<N>`.
Она показывает корреляцию одного запуска, без персональных данных.

В CI шаг `demo / smoke` дополнительно запускает `scripts/smoke_voice_contract.py`:
он создаёт голосовую сессию через запущенный Core и **настоящий Python AI**.
Только HTTP часть Media заменена коротким локальным сервером, который
проверяет фактические команды start/hangup; затем скрипт проверяет ingest и
повторное чтение событий Core. Локально запустите AI и Core с
`CORE_MEDIA_BASE_URL=http://127.0.0.1:18091`, затем:

```powershell
python scripts/smoke_voice_contract.py --core http://127.0.0.1:8080 --ai http://127.0.0.1:8090 --media-port 18091
```

Локальный результат 26.09: полный `./gradlew.bat test --no-daemon` —
`BUILD SUCCESSFUL`; контрактный прогон показал 7 событий для одной
коррелированной сессии. Отдельно запущенный Core на порту 18080 прошёл
карточный `python scripts/smoke_card_1050602.py --core
http://127.0.0.1:18080 --expect-fallback`: две завершённые сессии 1050602,
14 служб в каждой, одинаковый балл 100/100.

## Фактический конверт для publisher Media

Максиму нужен `POST http://core:8080/internal/v1/media/events` и переменная
`MEDIA_CORE_BASE_URL=http://core:8080` в Compose. Media отправляет полный
конверт, не обращаясь к PostgreSQL:

```json
{
  "eventId": "0b71143f-f8e0-4961-851d-dbc0984a7864",
  "sessionId": "123e4567-e89b-42d3-a456-426614174000",
  "type": "call.answered",
  "timestamp": "2026-09-26T12:00:00Z",
  "source": "media",
  "payload": {
    "callId": "a86c29f7-9b80-429f-8926-114ee491e7d2",
    "aiSessionId": "voice-123e4567-e89b-42d3-a456-426614174000",
    "channelId": "channel-1"
  }
}
```

При повторной отправке сохраняйте **тот же** `eventId` и все байты полей.
Core отвечает `200` с `accepted:false` для идентичного повтора, `409` — если
этот `eventId` уже занят другим содержимым. Для `transcript.final` добавьте
в payload `text`, `simulated` и границы реплики из ответа AI.

## Живой стенд

Реальный HTTP start Media реализован в #53. Для сквозного softphone-прогона
используйте [инструкцию Media](../services/media/docs/ai-websocket.md#softphone-smoke-с-событиями-core)
и `services/media/scripts/smoke_ai.py`: она сверяет две реплики, ID, события
Core и освобождение ресурсов после hangup. Это ручной gate #62.

На локальной машине проверки нет Docker, Go и Python-зависимостей AI, поэтому
здесь не запускались живые Asterisk/Media и реальная речь. CI запускает AI для
проверки создания сессии, а тестовый HTTP ответ Media не доказывает качество
RTP или звук в softphone; эти результаты должны быть приложены к #62.
