# События учебной сессии

## Конверт

```json
{
  "eventId": "0199d7b6-0000-7000-8000-000000000001",
  "sessionId": "0199d7b6-0000-7000-8000-000000000002",
  "type": "transcript.final",
  "timestamp": "2026-09-15T12:00:05.420Z",
  "source": "media",
  "payload": {}
}
```

События должны быть идемпотентными по `eventId`. Время передаётся в UTC в
формате RFC 3339. Kotlin Core сохраняет значимые события в `session_events`.

## Жизненный цикл

```text
CREATED -> READY -> RINGING -> ACTIVE -> COMPLETED -> SCORING -> SCORED
                     |           |            |
                     +--------> FAILED <------+
```

Для карточного режима переход `READY -> ACTIVE` выполняется без `RINGING`.

## Базовые события

| Тип | Источник | Назначение |
|---|---|---|
| `session.created` | core | teacher, student |
| `session.started` | core | teacher, student |
| `session.completed` | core | teacher, student |
| `call.ringing` | media | core |
| `call.answered` | media | core |
| `call.ended` | media | core |
| `transcript.partial` | media | core |
| `transcript.final` | media | core |
| `operator.speech_started` | media | core |
| `operator.speech_ended` | media | core |
| `caller.interrupted` | media | core |
| `operator.card_updated` | core | teacher |
| `operator.answer_submitted` | core | teacher |
| `score.started` | core | teacher, student |
| `score.completed` | core | teacher, student |
| `system.error` | any | core |

## Команды Core -> Media

- `call.start`
- `call.hangup`
- `speech.play`
- `speech.cancel`
- `recording.start`
- `recording.stop`
