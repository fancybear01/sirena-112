# Сирена-112

Учебный тренажёр для подготовки операторов дежурно-диспетчерских служб,
взаимодействующих с системой-112 города Москвы. Задача №9 хакатона
«Лидеры цифровой трансформации 2026». Команда «Ваш звонок важен для нас».

Курсант принимает вызов голосом или в карточном режиме, звонящего играет
AI-абонент, система сверяет карточку с официальным классификатором и выдаёт
объяснимый разбор по критериям. Всё работает **в изолированном контуре:
без интернета и без видеокарты.**

## Что умеет система

**Оператор-112 (STUDENT)**
- карточка происшествия по официальному классификатору: 1281 позиция,
  версия `046-2024-11-15`;
- признаки, обязательные вопросы, адрес, заявитель, пострадавшие;
- тип происшествия и состав служб вычисляет Core, а не выбирает курсант;
- живой голосовой разговор с AI-абонентом через SIP;
- таймер, живой статус назначенных служб ДДС, история попыток и обратная
  связь преподавателя.

**Преподаватель (TEACHER)**
- жизненный цикл сценария: создание, утверждение, назначение группе;
- импорт и экспорт сценариев с проверкой схемы и версии классификатора;
- мониторинг занятия в реальном времени по WebSocket;
- объяснимая оценка по 8 критериям и AI-разбор текста карточки;
- аналитика группы, графики и карта ошибок;
- экспертные комментарии и правки оценки с сохранением исходного отчёта;
- отчёты в XLSX и PDF, запись звонка в WAV;
- внешнее учебное табло без персональных данных.

**Администратор (ADMIN)**
- учётные записи, роли, группы, блокировка;
- состояние Core, AI, Media, PostgreSQL и Asterisk, CPU/RAM/диск, ошибки;
- запуск, остановка, перезапуск и обновление сервисов из интерфейса;
- ежедневный backup базы с доказанным восстановлением;
- метрики в формате Prometheus и отправка статуса во внешнюю систему.

## Измеренные показатели

| Показатель | Норматив | Результат |
| --- | --- | --- |
| Отклик API, p95 | ≤ 2 с | **0,14 с** |
| Ход разговора с AI-абонентом | ≤ 1,2 с | **0,5 с** |
| 20 занятий одновременно | ≤ 1,2 с | **0,67 с** на ход |
| Распознавание 3,3 с речи | — | **0,4 с** |
| Синтез ответа | — | **0,2 с** |

Полная матрица требований с доказательствами:
[`docs/requirements-coverage.md`](docs/requirements-coverage.md).

## Архитектура

```text
Браузер ──TLS──> Web (React + nginx)
                   │
                   ▼
               Kotlin Core ──> PostgreSQL ──> ежедневный backup
                │    │
                │    └──> Python AI: Vosk, Piper, AI-абонент, оценка
                │              ▲
                │              │ бинарный WebSocket, PCM
                └──> Go Media ─┘──> Asterisk: SIP, ARI, RTP
                        └──> запись занятия в WAV

Monitor: /metrics (Prometheus), /status, /push
Расширения: /api/ext/v1, версионированный API только для чтения
```

- `apps/web` — единый React-интерфейс с маршрутами `/admin`, `/teacher`, `/student`;
- `services/core` — Kotlin Core API, владелец бизнес-состояния и PostgreSQL;
- `services/media` — Go Media Gateway, SIP/ARI/RTP и потоковая обработка аудио;
- `services/ai` — локальные AI, STT и TTS на Python;
- `infra` — Docker Compose, PostgreSQL, Asterisk, мониторинг;
- `contracts` — OpenAPI, форматы событий и схема сценария;
- `docs` — архитектура, требования, замеры и журнал решений.

Подробно: [`docs/architecture.md`](docs/architecture.md).

## Правила взаимодействия

- Kotlin Core — единственный компонент, который изменяет бизнес-данные в PostgreSQL.
- Go передаёт медиасобытия и не принимает методических решений.
- Python получает необходимый контекст через внутренний API и не читает основную БД напрямую.
- В голосовом режиме Go напрямую обменивается с Python PCM-аудио и метаданными
  по бинарному WebSocket; Kotlin аудио не проксирует.
- Все интеграционные сообщения содержат `eventId`, `sessionId`, `type`, `timestamp` и `payload`.
- Межсервисные вызовы защищены отдельными Bearer-токенами.
- Вся конфигурация работает в изолированном локальном контуре.

Правила веток и Pull Request описаны в [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Быстрый старт

Полный автономный стенд Web + Core + AI + Media + Asterisk + PostgreSQL +
мониторинг. Windows:

```powershell
.\scripts\stack.ps1 init
.\scripts\stack.ps1 doctor
.\scripts\stack.ps1 start
.\scripts\stack.ps1 smoke
```

Ubuntu: те же действия через `bash scripts/stack.sh`. Штатный `start` ничего
не собирает и не скачивает: используются заранее загруженные образы и
локальные модели. PostgreSQL работает в именованном томе и переживает
`restart`/`stop`.

Шифрованный доступ из браузера:

```bash
sh scripts/make_tls_cert.sh
docker compose -f compose.yaml -f compose.tls.yaml up -d
# https://127.0.0.1:8443
```

Карточное демо Core + AI + Web одной командой:

```powershell
.\scripts\demo-card.ps1 start
```

Затем `http://localhost:5173/teacher` и `http://localhost:5173/student`.
Подробности — [`docs/demo-1050602.md`](docs/demo-1050602.md).

## Проверяемость

Каждый Pull Request проходит полный набор обязательных проверок без фильтров
по путям, чтобы изменение любого сервиса не могло пропустить регрессию
общего контракта:

- `validate` — формат имени ветки;
- `core / test` — unit- и integration-тесты Kotlin Core на Java 17;
- `ai / test` — Python-тесты;
- `web / test-build` — typecheck, тесты и production build Web;
- `media / test-build` — тесты, `go vet`, бинарник, Dockerfile Media,
  `docker compose config` и сборка Asterisk;
- `contracts / validate` — OpenAPI, JSON Schema, каталог и примеры сценариев;
- `demo / smoke` — два полных занятия `1050602` через реальные Core и AI;
- `demo / compose` — сборка и проверка карточного Docker Compose;
- `core / postgres-recovery` — восстановление состояния после перезапуска.

Запускаемые проверки на живом стенде:

| Что | Команда |
| --- | --- |
| сквозное занятие | `python scripts/smoke_card_1050602.py` |
| голосовой контракт | `python scripts/smoke_voice_contract.py` |
| нагрузка голосового тракта | `python scripts/load_voice_stack.py` |
| форматы данных | `python scripts/check_formats.py` |
| backup и восстановление | `python scripts/check_backup_restore.py` |
| TLS | `python scripts/check_tls.py` |
| API расширений | `python scripts/ext_api_client.py` |
| покрытие требований | `python scripts/check_coverage.py` |

## Документация

| Тема | Документ |
| --- | --- |
| Требования и покрытие | [`requirements.md`](docs/requirements.md), [`requirements-coverage.md`](docs/requirements-coverage.md) |
| Архитектура и решения | [`architecture.md`](docs/architecture.md), [`decisions.md`](docs/decisions.md) |
| Демо и сценарии | [`demo-1050602.md`](docs/demo-1050602.md), [`scenario-workflow.md`](docs/scenario-workflow.md), [`scenario-import-export-77.md`](docs/scenario-import-export-77.md) |
| Голос | [`voice-two-turns.md`](docs/voice-two-turns.md), [`voice-shipping-stack.md`](docs/voice-shipping-stack.md), [`voice-contract-68.md`](docs/voice-contract-68.md), [`voice-ws-for-media.md`](docs/voice-ws-for-media.md), [`voice-readiness.md`](docs/voice-readiness.md) |
| AI и оценка | [`ai-benchmark.md`](docs/ai-benchmark.md), [`ai-text-review.md`](docs/ai-text-review.md), [`ai-load.md`](docs/ai-load.md) |
| Обучение и аналитика | [`training-analytics-75.md`](docs/training-analytics-75.md), [`training-history.md`](docs/training-history.md) |
| Безопасность | [`auth-rbac.md`](docs/auth-rbac.md), [`tls.md`](docs/tls.md), [`security-recordings-task.md`](docs/security-recordings-task.md) |
| Эксплуатация | [`offline-full-stack.md`](docs/offline-full-stack.md), [`admin-operations.md`](docs/admin-operations.md), [`backup-restore.md`](docs/backup-restore.md), [`monitoring-integration.md`](docs/monitoring-integration.md), [`media-load.md`](docs/media-load.md) |
| Данные и интеграции | [`format-matrix.md`](docs/format-matrix.md), [`postgres-core.md`](docs/postgres-core.md), [`extension-api.md`](docs/extension-api.md), [`contracts/`](contracts/README.md) |
| Сервисы | [`core`](services/core/README.md), [`ai`](services/ai/README.md), [`media`](services/media/README.md), [`web`](apps/web/README.md), [`asterisk`](infra/asterisk/README.md) |
| Презентация | [`presentation-content.md`](docs/presentation-content.md) |
