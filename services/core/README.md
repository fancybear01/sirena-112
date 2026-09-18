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

`AiClient` и `MediaClient` представлены `MockAiClient` и `MockMediaClient`.
Они не выполняют сетевых вызовов, поэтому Core запускается без Python AI и Go
Media; реальные адаптеры можно подключить через те же интерфейсы.
