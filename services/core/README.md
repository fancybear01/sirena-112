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
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready
curl http://localhost:8080/actuator/health
```

Настройки берутся из окружения: `CORE_PORT`, `CORE_ENVIRONMENT` и
`CORE_VERSION`. Все ответы имеют JSON-формат, а запросы получают
корреляционный заголовок `X-Request-ID`; логи выводятся в JSON и включают этот
идентификатор.
