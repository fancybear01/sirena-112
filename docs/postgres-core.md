# PostgreSQL для Kotlin Core

## Запуск

Основной локальный контур запускает Core с PostgreSQL и миграциями:

```powershell
docker compose up -d --build postgres core
```

Core ждёт healthcheck PostgreSQL, применяет Flyway-миграции из
`services/core/src/main/resources/db/migration` и отвечает на
`http://localhost:8080/ready`. Учётные данные задаются только переменными
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` в локальном `.env`; не
публикуйте рабочий `.env` в Git.

Для запуска Core вне Docker используйте отдельный свободный порт PostgreSQL:

```powershell
$env:CORE_STORAGE = 'postgres'
$env:CORE_FLYWAY_ENABLED = 'true'
$env:CORE_DATABASE_URL = 'jdbc:postgresql://127.0.0.1:5433/sirena112'
$env:CORE_DATABASE_USERNAME = 'sirena112'
$env:CORE_DATABASE_PASSWORD = '<локальный пароль>'
cd services/core
.\gradlew.bat bootRun
```

## Что хранится

Миграция `V1` создаёт таблицы `scenarios`, `training_sessions`,
`session_events`, `session_reports`, `service_assignments`. JSONB-снимки
сохраняют контрактные данные карточки и отчёта без потери полей, а отдельные
ключи и индексы позволяют обеспечить уникальный `event_id`, запросить историю
сессии и сохранить назначение ДДС. Сценарии-фикстуры загружаются идемпотентно.

После рестарта Core доступны незавершённые и завершённые сессии, их карточки,
отчёты, события и назначения служб. Повторная отправка карточки не создаёт
второй набор назначений: проверяется наличие назначений для `session_id`.

## Резервное копирование

Временная учебная команда:

```powershell
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backup.sql
```

Восстановление выполняйте только в пустую тестовую БД после остановки Core:

```powershell
Get-Content backup.sql | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Файл дампа может содержать учебные персональные данные: храните его локально в
защищённом месте, не добавляйте в репозиторий и не пересылайте без обезличивания.
