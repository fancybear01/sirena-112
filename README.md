# Сирена-112

Учебный симулятор для подготовки операторов дежурно-диспетчерских служб,
взаимодействующих с системой-112 города Москвы. Проект разрабатывается для
задачи №9 хакатона «Лидеры цифровой трансформации 2026».

## Цель первой вертикальной версии

1. Преподаватель выбирает утверждённый сценарий и запускает занятие.
2. Обучающийся фиксирует признаки, ответы, адрес и сведения о заявителе и
   пострадавших; тип происшествия и службы вычисляет Kotlin Core.
3. Core/AI сравнивает карточку с эталоном и формирует объяснимый отчёт.
4. Преподаватель видит результат и журнал действий.

После стабилизации карточного режима добавляется голосовой вызов через
локальный SIP-сервер.

## Архитектура

- `apps/web` — единый React-интерфейс с маршрутами `/admin`, `/teacher`, `/student`;
- `services/core` — Kotlin Core API, владелец бизнес-состояния и PostgreSQL;
- `services/media` — Go Media Gateway, SIP/ARI/RTP и потоковая обработка аудио;
- `services/ai` — локальные AI, STT и TTS на Python;
- `infra` — Docker Compose, PostgreSQL и конфигурация Asterisk;
- `contracts` — OpenAPI, форматы событий и схема сценария;
- `docs` — архитектура, требования и журнал решений.

## Правила взаимодействия

- Kotlin Core — единственный компонент, который изменяет бизнес-данные в PostgreSQL.
- Go передаёт медиасобытия и не принимает методических решений.
- Python получает необходимый контекст через внутренний API и не читает основную БД напрямую.
- В голосовом режиме Go напрямую обменивается с Python PCM-аудио и метаданными
  по бинарному WebSocket; Kotlin аудио не проксирует.
- Все интеграционные сообщения содержат `eventId`, `sessionId`, `type`, `timestamp` и `payload`.
- Итоговая конфигурация должна работать в изолированном локальном контуре.

Правила веток и Pull Request описаны в [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Обязательные проверки Pull Request

Перед merge каждый Pull Request должен пройти один и тот же полный набор
проверок; фильтры по путям намеренно не используются, чтобы изменение любого
сервиса не могло пропустить регрессию общего контракта:

- `validate` (workflow `branch-name`) — формат имени ветки; имя сохранено для действующей защиты main;
- `core / test` — unit- и integration-тесты Kotlin Core на Java 17;
- `ai / test` — Python-тесты с dev-зависимостями;
- `web / test-build` — typecheck, тесты и production build Web;
- `media / test-build` — тесты, `go vet`, бинарник, Dockerfile Media,
  `docker compose config` и сборка Asterisk без публикации образов;
- `contracts / validate` — OpenAPI, JSON Schema, каталог и примеры сценариев.
- `demo / smoke` — два полных занятия `1050602` через реальные Core и AI.

Дополнительно `demo / compose` собирает и проверяет отдельный Docker Compose для
карточного демо; пока этот новый check не добавлен в required status checks.

Имена jobs уникальны между workflows. Все перечисленные check names должны быть добавлены как required status checks
в правила защиты ветки `main`. Workflow запускаются для Pull Request и push в
`main`, используют кэши только для зависимостей и отменяют устаревший запуск для
той же ветки.

## Локальная инфраструктура

Единый автономный стенд Web + Core + AI + Media + Asterisk + PostgreSQL +
мониторинг, подготовка `offline-bundle`, команды Windows/Ubuntu, smoke-тесты и
диагностика описаны в [`docs/offline-full-stack.md`](docs/offline-full-stack.md).

После подготовки образов и моделей локальный запуск на Windows выполняется так:

```powershell
.\scripts\stack.ps1 init
.\scripts\stack.ps1 doctor
.\scripts\stack.ps1 start
.\scripts\stack.ps1 smoke
```

На Ubuntu используйте те же действия через `bash scripts/stack.sh`. Штатный
`start` не собирает и не скачивает ничего: используются только заранее
загруженные образы и локальные модели. PostgreSQL работает в именованном томе и
переживает `restart`/`stop`.

Asterisk (SIP + ARI): [`infra/asterisk/README.md`](infra/asterisk/README.md).  
Media Gateway: [`services/media/README.md`](services/media/README.md), контракт [`contracts/media-core.md`](contracts/media-core.md).

Карточное демо Core + AI + Web запускается отдельно от голосового стека одной
командой PowerShell (Docker Desktop должен быть запущен):

```powershell
.\scripts\demo-card.ps1 start
```

После успешного smoke откройте `http://localhost:5173/teacher` и
`http://localhost:5173/student`. Остановка: `.\scripts\demo-card.ps1 stop`.
Команда останавливает только контейнеры `sirena-card`; данные и контейнеры
голосового стека не затрагиваются. Подробности и запуск без Docker — в
[`docs/demo-1050602.md`](docs/demo-1050602.md).

## Ближайшая контрольная точка

Сквозной карточный сценарий `1050602` доступен через реальные Core, AI и Web.
Команды запуска, автоматическая проверка и сценарий показа — в
[`docs/demo-1050602.md`](docs/demo-1050602.md). Отдельно развивается SIP-вызов с
возвратом тестового аудио.
