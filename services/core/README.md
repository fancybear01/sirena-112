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
