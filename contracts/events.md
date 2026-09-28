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
| `media.error` | media | core |
| `media.latency` | media | core |
| `transcript.partial` | media | core |
| `transcript.final` | media | core |
| `recording.ready` | media | core |
| `operator.speech_started` | media | core |
| `operator.speech_ended` | media | core |
| `caller.interrupted` | media | core |
| `operator.card_updated` | core | teacher |
| `card.answers_updated` | core | teacher, student |
| `routing.calculated` | core | teacher, student |
| `service.assigned` | core | teacher, student |
| `service.status_changed` | core | teacher, student |
| `card.time_limit_exceeded` | core | teacher, student |
| `operator.answer_submitted` | core | teacher |
| `score.started` | core | teacher, student |
| `score.completed` | core | teacher, student |
| `system.error` | any | core |

`transcript.*` фактически формирует Python AI, но наружу в Core его публикует
Media, поэтому в конверте используется `source: "media"`. `eventId` создаёт
Media; в `payload` передаются `aiSessionId`, текст, признак финальности и
временные границы фразы. Python не отправляет эти события в Core напрямую.

## Назначения и статусы ДДС (#37)

После проверки и отправки карточки Core фиксирует адресатов последней вычисленной
маршрутизации: по одному `service.assigned` на уникальный serviceId. Пересчёт
черновика не оповещает службы. Назначение сохраняет cardRevision отправленной карточки.
Пустой набор служб допустим и не создаёт фиктивных назначений.

Оба события используют общий конверт, `source: core`; источник учебного изменения
находится в `payload.changeSource` (SYSTEM при создании, MOCK через mock API;
TEACHER и SERVICE зарезервированы). `eventId` совпадает с ID записи истории.

```json
{
  "eventId": "eaa138be-2d41-42d3-80d0-f7c4df6a0ba2",
  "sessionId": "0199d7b6-0000-7000-8000-000000000002",
  "type": "service.status_changed",
  "timestamp": "2026-09-19T00:00:05Z",
  "source": "core",
  "payload": {
    "assignmentId": "ad6138be-2d41-42d3-80d0-f7c4df6a0ba2",
    "serviceId": "MCHS",
    "cardRevision": 1,
    "deadlineAt": "2026-09-19T01:00:00Z",
    "sequence": 2,
    "fromStatus": "ADDED",
    "status": "RECEIVED",
    "changeSource": "MOCK",
    "comment": "Получено диспетчером",
    "refusalReason": null
  }
}
```

У `service.assigned`: sequence=1, fromStatus=null, status=ADDED, changeSource=SYSTEM.
Последовательность определяется sequence внутри назначения; timestamp может совпадать.
Повтор eventId явно отклоняется с 409, без повторной публикации и изменения истории.
Существующий `/ws/sessions/{sessionId}/events` доставляет новые события и replay.
Клиенту нужно дедуплицировать replay по eventId.

`overdue` вычисляется при чтении, не вызывает смену статуса и не создаёт событие:
UI может отсчитывать время до deadlineAt локально. Закрытые назначения сохраняют
всю историю; позднее завершение видно по времени перехода относительно deadlineAt.

## События карточки и маршрутизации

Core публикует эти события после успешного сохранения карточки. Они не дают
клиенту права подменить вычисленные поля: payload отражает решение Core для
конкретной ревизии карточки.

### card.answers_updated

    {
      "sessionId": "0199d7b6-0000-7000-8000-000000000002",
      "type": "card.answers_updated",
      "source": "core",
      "payload": {
        "cardRevision": 3,
        "selectedSignIds": [
          "sign.object.residential-building",
          "sign.location.garbage-chute",
          "sign.fire.smoke"
        ],
        "answeredQuestionIds": ["victims.present"]
      }
    }

### routing.calculated

    {
      "sessionId": "0199d7b6-0000-7000-8000-000000000002",
      "type": "routing.calculated",
      "source": "core",
      "payload": {
        "cardRevision": 3,
        "status": "RESOLVED",
        "classifierVersion": "046-2024-11-15",
        "classifierCode": "1050602",
        "incidentType": "задымление: мусоропровод",
        "ekp35IncidentType": "пожар: мусоропровод",
        "responseScenarioCode": "1_9",
        "serviceIds": ["MCHS"],
        "missingInputIds": []
      }
    }

При INCOMPLETE код и службы могут быть null/пустыми, а missingInputIds
содержит идентификаторы признаков или вопросов, которые нужно заполнить.

### card.time_limit_exceeded

    {
      "sessionId": "0199d7b6-0000-7000-8000-000000000002",
      "type": "card.time_limit_exceeded",
      "source": "core",
      "payload": {
        "timeLimitSeconds": 600,
        "elapsedSeconds": 601,
        "cardRevision": 3
      }
    }

Core отправляет событие не более одного раза для одной сессии. Факт превышения
также возвращается в Session.timeLimitExceeded и доступен AI в отчёте.

## Команды Core -> Media

- `call.start`
- `call.hangup`
- `speech.play`
- `speech.cancel`
- `recording.start`
- `recording.stop`

Команда `call.start` должна содержать как минимум `sessionId`, `aiSessionId` и
SIP-адрес назначения. `aiSessionId` предварительно получает Core при создании
AI-сессии.
