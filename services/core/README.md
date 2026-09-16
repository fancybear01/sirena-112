# Core

Kotlin Core API является единственным источником истины для учебной сессии.

Ответственность:

- аутентификация и RBAC;
- пользователи, группы и назначения;
- сценарии и эталоны;
- учебные сессии и конечный автомат;
- карточки происшествий;
- формальная оценка;
- журнал событий и отчёты;
- интеграция с AI и Media Gateway.

Только этот сервис получает доступ к основной схеме PostgreSQL.

## Быстрый запуск

Требуется JDK 11+ и Gradle 8+:

```bash
gradle bootRun
```

В `settings.gradle.kts` первым указан `repo1.maven.org` — это тот же Maven
Central, но он обходится без сетевой проблемы, при которой некоторые
окружения возвращают Gradle ошибку `403` на `repo.maven.apache.org`.

По умолчанию API слушает `http://localhost:8080`.

Проверки запуска:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready
curl http://localhost:8080/actuator/health
```

Настройки берутся из окружения: `CORE_PORT`, `CORE_ENVIRONMENT`,
`CORE_VERSION`, `CORE_AI_BASE_URL` и `CORE_MEDIA_BASE_URL`. Все ответы имеют
JSON-формат, а запросы получают корреляционный заголовок `X-Request-ID`.
При передаче `X-Session-ID` он добавляется в MDC; JSON-логи включают оба
идентификатора.

Для воспроизводимого запуска в репозитории есть Gradle Wrapper 8.8:

```bash
./gradlew test
./gradlew bootRun
```

## Доменная модель учебной сессии

Состояние `TrainingSession` меняется только доменными методами и соответствует
`contracts/events.md`:

```text
CREATED -> READY -> RINGING -> ACTIVE -> COMPLETED -> SCORING -> SCORED
                     |           |            |
                     +--------> FAILED <------+
```

В `SessionMode.CARD` сессия переходит из `READY` сразу в `ACTIVE`; звонковые
переходы доступны только в `SessionMode.VOICE`. `Scenario`, `OperatorCard` и
конверт `SessionEvent` используют поля актуального сценарного и событийного
контрактов, включая `groundTruth.signs` и `ekpCode`.

Пока PostgreSQL ещё не подключён, доступны интерфейсы
`ScenarioRepository`, `TrainingSessionRepository` и `SessionEventRepository` с
потокобезопасными in-memory реализациями. Репозиторий событий идемпотентен по
`eventId`, поэтому его можно заменить на PostgreSQL без изменения доменной
логики.

## Карточный учебный сценарий (задача #7)

Сквозной сценарий доступен без внешних сервисов и использует утверждённый
mock-сценарий. Идентификатор сценария можно получить первым запросом:

```bash
curl http://localhost:8080/api/teacher/scenarios
```

Далее выполните последовательность (подставьте `SESSION_ID` из ответа на
создание сессии):

```bash
curl -X POST http://localhost:8080/api/teacher/sessions \
  -H 'Content-Type: application/json' -d '{}'
curl -X POST http://localhost:8080/api/teacher/sessions/SESSION_ID/start
curl -X PATCH http://localhost:8080/api/student/sessions/SESSION_ID/card \
  -H 'Content-Type: application/json' \
  -d '{"incidentType":"задымление: мусоропровод","signs":{"level1":"жилой дом","level2":"мусоропровод","level3":"дым"},"address":"Москва, ул. Берзарина, д. 21, корп. 1, под. 3","requiredServices":["Служба 101","ДДС района","МОЭК"]}'
curl -X POST http://localhost:8080/api/teacher/sessions/SESSION_ID/stop
curl -X POST http://localhost:8080/api/student/sessions/SESSION_ID/submit
curl http://localhost:8080/api/teacher/sessions/SESSION_ID/report
```

Отчёт содержит итоговый `score`, критерии с баллами, `errors` и
`recommendations`. Пустая карточка отклоняется с HTTP 400.

## События сессии и mock-интеграции

Frontend может подписаться на события конкретной сессии:

```text
ws://localhost:8080/ws/sessions/{sessionId}/events
```

При подключении Core сначала отправляет сохранённую историю, затем каждое
новое событие. Сообщения — JSON-конверты из `contracts/events.md`, например:

```json
{
  "eventId": "0199d7b6-0000-7000-8000-000000000001",
  "sessionId": "0199d7b6-0000-7000-8000-000000000002",
  "type": "operator.card_updated",
  "timestamp": "2026-09-15T12:00:05.420Z",
  "source": "core",
  "payload": {}
}
```

`AiClient` и `MediaClient` представлены `MockAiClient` и `MockMediaClient`.
Они не выполняют сетевых вызовов, поэтому Core запускается без Python AI и Go
Media; реальные адаптеры можно подключить через те же интерфейсы.
