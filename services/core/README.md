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
`CORE_VERSION`, `CORE_AI_BASE_URL`, `CORE_MEDIA_BASE_URL` и `CORE_MEDIA_MODE`
(`http` по умолчанию, `mock` для локальных тестов). Все ответы имеют
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
конверт `SessionEvent` используют поля контрактов 0.3 (`contracts/openapi.yaml`,
`contracts/events.md`): эталон сценария - `GroundTruthV2` с кодом
классификатора и вычисленным списком служб, карточка - исходные данные
оператора `OperatorCardInput` плюс результат вычисления `CardCalculation`.

Пока PostgreSQL ещё не подключён, доступны интерфейсы
`ScenarioRepository`, `TrainingSessionRepository` и `SessionEventRepository` с
потокобезопасными in-memory реализациями. Репозиторий событий идемпотентен по
`eventId`, поэтому его можно заменить на PostgreSQL без изменения доменной
логики.

## Классификатор и маршрутизация (задачи #32/#33)

Тип происшествия и службы вычисляет Core, а не клиент. Источник данных -
нормализованный каталог `contracts/catalog/classifier-v046-11.json` из задачи
#32; он загружается один раз при старте через `ClassifierCatalog` (путь ищется
от текущего каталога вверх до `contracts/catalog/`, переопределяется
свойством `core.classifier-catalog-path`). XLSX во время работы не читается.

Семантика вычисления (`ClassificationEngine`) повторяет референсный
интерпретатор `tools/classifier-import/examples.py`:

- запись каталога находится точным совпадением полного пути признаков
  (уровни 1-3 без пропусков; неполный путь - статус `INCOMPLETE`,
  чужая комбинация - `NO_MATCH`);
- условные колонки служб применяются как правила: опровергнутое условие
  пропускает правило, неотвеченное условие или `requiresReview` оставляет его
  неразрешённым, `DO_NOT_NOTIFY` запрещает службу, одновременное совпадение
  NOTIFY и DO_NOT_NOTIFY - конфликт на методический разбор;
- неотвеченный вопрос - неизвестное значение, а не `false`/`NONE`;
- каждая направленная служба несёт причины `reasons` (правило, колонка,
  совпавшие входы), а в `explanations` попадают неразрешённые правила и
  предупреждения импорта.

Учебные сценарии (включая эталон 1050602) загружаются из
`contracts/examples/scenario-*.json` - файлов, сгенерированных из каталога;
списки служб в эталоне не заданы вручную.

## Карточный учебный сценарий (контракт 0.3)

Сквозной сценарий доступен без внешних сервисов. Идентификатор сценария можно
получить первым запросом:

```bash
curl http://localhost:8080/api/teacher/scenarios
```

Далее выполните последовательность (подставьте `SESSION_ID` из ответа на
создание сессии):

```bash
curl -X POST http://localhost:8080/api/teacher/sessions -H 'Content-Type: application/json' -d '{}'
curl -X POST http://localhost:8080/api/teacher/sessions/SESSION_ID/start
```

Форма для черновика - допустимые признаки по уровням и зависимые вопросы
маршрутизации (следующий уровень зависит от выбранного родителя):

```bash
curl http://localhost:8080/api/student/sessions/SESSION_ID/card-form
```

Черновик можно сохранять частично; клиент отправляет только исходные данные
оператора (`selectedSignIds`, `answers`, адрес, пострадавшие), а тип и службы
Core вычисляет сам и возвращает в `card.calculation`:

```bash
curl -X PATCH http://localhost:8080/api/student/sessions/SESSION_ID/card \
  -H 'Content-Type: application/json' \
  -d '{"input":{"incident":{"selectedSignIds":["sign.68eaae1dc9472ce9","sign.8795ab4a7bb0d66a","sign.8b0cf230ebb8ba99"],"answers":[{"questionId":"routing.victims-status","optionIds":["NONE"]},{"questionId":"routing.no-access","optionIds":["NO"]},{"questionId":"routing.evacuation","optionIds":["NO"]},{"questionId":"routing.medical-help","optionIds":["NO"]},{"questionId":"routing.threat-to-people","optionIds":["NO"]},{"questionId":"routing.offence","optionIds":["NO"]},{"questionId":"routing.traffic-blocked","optionIds":["NO"]},{"questionId":"routing.culture-listed-facility","optionIds":["NO"]}]},"address":{"displayAddress":"Учебный адрес, дом 1"},"victims":{"present":false}}}'
```

Отправка на оценку требует заполненных обязательных полей (полный путь
признаков со статусом `RESOLVED`, адрес, `victims.present`, ответы на все
вопросы маршрутизации записи):

```bash
curl -X POST http://localhost:8080/api/teacher/sessions/SESSION_ID/stop
curl -X POST http://localhost:8080/api/student/sessions/SESSION_ID/submit \
  -H 'Content-Type: application/json' \
  -d '{"input":{ /* те же исходные данные */ }}'
curl http://localhost:8080/api/teacher/sessions/SESSION_ID/report
```

Отчёт содержит итоговый `score`, критерии с баллами (`SIGNS`, `ANSWERS`,
`SERVICES`, `ADDRESS`), `errors`, `recommendations` и ссылку на версию
классификатора с кодом эталона. Пустая карточка отклоняется с HTTP 400,
незаполненные обязательные поля - тоже, но уже на submit.

Вычисляемые поля (`incidentType`, `requiredServices`, `classifierCode` и
другие) в `input` запрещены: тела запросов разбираются строго, подмена
отклоняется с HTTP 400. `expectedRevision` защищает черновик от перезаписи
устаревшей версией (HTTP 409 при конфликте).

## События сессии и mock-интеграции

Frontend может подписаться на события конкретной сессии:

```text
ws://localhost:8080/ws/sessions/{sessionId}/events
```

При подключении Core сначала отправляет сохранённую историю, затем каждое
новое событие. Сообщения - JSON-конверты из `contracts/events.md`. При
сохранении карточки Core публикует `card.answers_updated` (ревизия, выбранные
признаки, отвеченные вопросы) и `routing.calculated` (статус, код, тип, ЕКП-35,
сценарий реагирования, итоговые службы, недостающие входы), затем устаревший
для совместимости `operator.card_updated`; при превышении лимита времени -
однократный `card.time_limit_exceeded`:

```json
{
  "eventId": "0199d7b6-0000-7000-8000-000000000001",
  "sessionId": "0199d7b6-0000-7000-8000-000000000002",
  "type": "routing.calculated",
  "timestamp": "2026-09-15T12:00:05.420Z",
  "source": "core",
  "payload": {
    "cardRevision": 1,
    "status": "RESOLVED",
    "classifierVersion": "046-2024-11-15",
    "classifierCode": "1050602",
    "incidentType": "задымление: мусоропровод",
    "ekp35IncidentType": "пожар: мусоропровод",
    "responseScenarioCode": "1_9",
    "serviceIds": ["MCHS", "ZODD", "..."],
    "missingInputIds": []
  }
}
```

Карточный сценарий не требует доступности AI: оценка при сбое возвращается к
упрощённой логике Core. Голосовой сценарий использует реальные HTTP-клиенты AI
и Media; только Media можно перевести в `CORE_MEDIA_MODE=mock` для локальных тестов.

## Голосовая сессия (#54)

Создайте сессию с `mode: VOICE` (при отсутствии `mode` остаётся `CARD`), затем
начните звонок. `scenarioId` можно опустить для сценария по умолчанию 1050602.

```http
POST /api/teacher/sessions
Content-Type: application/json

{"mode":"VOICE"}
```

```http
POST /api/teacher/sessions/{sessionId}/call/start
Content-Type: application/json

{"sipAddress":"PJSIP/1001"}
```

Core сначала вызывает `POST /ai/voice/sessions` с полным сценарием, получает
`aiSessionId`, затем отправляет `POST /internal/v1/calls/start` в Media с
`sessionId`, `aiSessionId`, `sipAddress`. Ответ `202` содержит `callId` и
техническое состояние `RINGING`. Бизнес-сессия перейдёт в `ACTIVE` только после
`call.answered` от Media. Ошибки AI/Media возвращаются как `503`, конфликт
активного звонка — `409`, несоответствие ответа контракту — `502`.

Media отправляет конверты `call.ringing`, `call.answered`, `call.ended`,
`media.error` и `transcript.*` в `POST /internal/v1/media/events`. Core сверяет
`sessionId`, `callId`, `aiSessionId`, подавляет повтор `eventId`, сохраняет
события и транслирует их в `/ws/sessions/{sessionId}/events`. История доступна
через `GET /api/teacher/sessions/{sessionId}/events`; состояние звонка — через
`GET /api/teacher/sessions/{sessionId}/call`.

`POST /api/teacher/sessions/{sessionId}/call/hangup` посылает команду Media и
идемпотентен после подтверждённого завершения. Само состояние учебной сессии
меняется только после события `call.ended`. Карточный `/start` и `/stop` для
VOICE отклоняются; список карточных назначений VOICE не включает.

Голосовые сессии и журнал событий пока in-memory. Конечная сквозная проверка
реального звука требует Media RTP ↔ AI bridge (#53) и подключения Media event
publisher к указанному HTTP endpoint; тесты Core используют подставные AI/Media.
## Назначения ДДС — задача #37

После успешного `POST /api/student/sessions/{sessionId}/submit` создаются назначения
для `calculation.services` отправленной карточки. Сохранение черновика и вычисление
маршрутизации сами по себе не считаются оповещением. Повторное внутреннее создание
идемпотентно; состав адресатов и cardRevision фиксируются один раз. Реальные службы
не вызываются. Назначения и история пока **in-memory**, как сессии: переживают
повторные HTTP-запросы, но не перезапуск процесса. Контакты ведомств не выдумываются.

Чтение: `GET /api/student/sessions/{sessionId}/service-assignments` или такой же
путь `/api/teacher/...`. До отправки карточки — `[]`, неизвестная сессия — 404.
Полная история включена в каждое назначение. Общий WebSocket
`/ws/sessions/{sessionId}/events` передаёт `service.assigned` и `service.status_changed`.

Автомат переходов:

- `ADDED → RECEIVED → ACCEPTED → RESPONDING → ARRIVED → COMPLETED`.
- Из RECEIVED и ACCEPTED можно перейти в REFUSED (непустая refusalReason обязательна).
- Из любого незакрытого статуса можно перейти в FAILED.
- COMPLETED, REFUSED, FAILED — терминальные; повтор статуса/недопустимый переход — 409.
- Каждый переход сохраняет eventId, sequence, timestamp UTC, источник и комментарий.
  Повтор eventId явно отклоняется с 409 без изменения истории, даже для другой службы.

Статусы служб независимы друг от друга и от TrainingSession.state: учебная сессия
может быть SCORED, а службы ещё реагировать. `CORE_SERVICE_ASSIGNMENT_DEADLINE_SECONDS`
(по умолчанию 3600, строго >0) задаёт срок с момента назначения. `overdue=true`
означает «не завершено в срок» для незакрытого назначения. Просрочка не подменяет
статус, не дописывает историю и не запускает фоновых уведомлений. Для завершённых
история позволяет проверить, был ли переход выполнен после deadlineAt.

Для локальной симуляции в PowerShell перед запуском Core:

```powershell
$env:CORE_SERVICE_ASSIGNMENT_MOCK_UPDATES_ENABLED = 'true'
$env:CORE_SERVICE_ASSIGNMENT_DEADLINE_SECONDS = '120'
.\gradlew.bat bootRun
```

После отправки карточки получите sessionId и assignmentId через API чтения, затем:

```http
POST /api/mock/sessions/{sessionId}/service-assignments/{assignmentId}/status
Content-Type: application/json

{"eventId":"eaa138be-2d41-42d3-80d0-f7c4df6a0ba2","status":"RECEIVED","comment":"Получено диспетчером"}
```

Для каждого следующего перехода используйте новый UUID. Источник сервер фиксирует
как MOCK, передать source/timestamp/status истории из клиента нельзя. Mock endpoint
отключён по умолчанию (404); включать только на изолированном учебном стенде:
авторизация и реальная интеграция ДДС в эту задачу не входят. OpenAPI/Swagger-примеры:
`contracts/openapi.yaml`; конверты: `contracts/events.md`.
