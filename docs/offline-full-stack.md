# Полный автономный стенд Sirena-112

Этот регламент поднимает локально Web, Core, AI с настоящими Vosk/Piper,
Media Gateway, Asterisk, PostgreSQL и мониторинг. На целевой машине сеть не
нужна: Docker-образы, модели и команды запуска входят в `offline-bundle`.

## Что входит в стенд

| Компонент | Назначение | Закреплённая основа |
|---|---|---|
| Web | production React UI и proxy `/api`, `/ws` | Node 22 и nginx 1.29 по digest |
| Core | бизнес-состояние и REST API | Eclipse Temurin 17 по digest |
| AI | карточный движок, Vosk STT, Piper TTS | Python 3.11 по digest, `vosk==0.3.45`, `piper-tts==1.2.0` |
| Media | ARI, RTP и бинарный WebSocket к AI | Go 1.26.5 и Alpine 3.20 по digest |
| Asterisk | локальные SIP, ARI и RTP | Asterisk 20 по digest |
| PostgreSQL | постоянное состояние Core | PostgreSQL 16 Alpine по digest |
| Monitor | единый readiness JSON | Python 3.12 по digest |
| Smoke | карточная и голосовая самопроверки | Python 3.12 по digest |

Точные digests находятся в Dockerfile и `compose.yaml`. Модели закреплены URL,
ревизией и SHA-256 в `infra/offline/models.env`:

- `vosk-model-small-ru-0.22`;
- `ru_RU-dmitri-medium.onnx` и его JSON-конфигурация.

Ни модели, ни зависимости не скачиваются во время штатного запуска.

## Требования

Машина подготовки пакета должна иметь доступ в интернет, Git-репозиторий,
Docker Engine с Compose v2, PowerShell 5.1+ на Windows либо Bash, `curl`,
`sha256sum` и `unzip` на Ubuntu.

Целевая офлайн-машина:

- Windows 10/11 x86-64 с Docker Desktop (Linux containers) либо Ubuntu 20.04+
  x86-64 с Docker Engine и Compose v2;
- Python 3 для локального admin helper;
- минимум 4 CPU, 8 ГБ памяти, доступной Docker, и 4 ГБ свободного места;
- свободные TCP-порты 5173, 8080, 8088, 8090, 8091, 8099, 8100, 5432 и 5060;
- свободные UDP-порты 5060 и 10000-10100.

GPU не требуется. Все HTTP, SIP, RTP и служебные порты доступны только на
loopback. Автономный профиль требует `SIRENA_BIND_ADDRESS=127.0.0.1` и
отказывается запускаться с другим адресом.

## 1. Подготовка офлайн-пакета

Выполняется один раз на машине с интернетом из корня репозитория.

Windows PowerShell:

```powershell
.\scripts\prepare-offline.ps1
```

Ubuntu:

```bash
bash scripts/prepare-offline.sh
```

Команда проверяет SHA-256 моделей, собирает все образы и создаёт исключённый из
Git каталог `offline-bundle`:

```text
offline-bundle/
  images.tar
  models/
  scripts/stack.ps1
  scripts/stack.sh
  scripts/admin_helper.py
  compose.yaml
  compose.offline.yaml
  .env.example
  SHA256SUMS
  VERSION
  docs/offline-full-stack.md
  docs/admin-operations.md
```

Секретный `.env` в пакет намеренно не входит. Не помещайте в пакет реальные
ФИО, телефоны, записи разговоров или иные персональные данные.

Перенесите весь каталог на целевую машину. Для съёмного носителя рекомендуется
шифрование средствами организации.

## 2. Проверка и загрузка на офлайн-машине

На Ubuntu сначала проверьте пакет:

```bash
cd offline-bundle
bash scripts/verify-bundle.sh
docker load --input images.tar
bash scripts/stack.sh init
bash scripts/stack.sh doctor
```

На Windows откройте PowerShell в `offline-bundle`:

```powershell
.\scripts\verify-bundle.ps1
docker load --input .\images.tar
.\scripts\stack.ps1 init
.\scripts\stack.ps1 doctor
```

Проверка охватывает образы, конфигурацию, скрипты и каждый файл моделей. `init`
создаёт локальный `.env` со случайными секретами и никогда не перезаписывает
существующий файл. `doctor`
проверяет Docker, Compose, секреты, модели, образы, конфигурацию и занятые
порты. Все ошибки содержат имя отсутствующего образа/модели либо номер порта.

## 3. Запуск и проверка

Windows:

```powershell
.\scripts\stack.ps1 start
.\scripts\stack.ps1 status
.\scripts\stack.ps1 smoke
```

Ubuntu:

```bash
bash scripts/stack.sh start
bash scripts/stack.sh status
bash scripts/stack.sh smoke
```

`start` всегда использует `--no-build --pull never`: обращение к registry и
сборка на целевой машине запрещены. Первый запуск на машине без тома является
чистым развёртыванием; Flyway автоматически создаёт схему PostgreSQL.

Успешный `smoke` должен завершиться двумя строками `PASS`:

- карточный сценарий `1050602` проходит через настоящие Core и AI;
- голосовой loopback-вызов проходит через Core → Asterisk → RTP → Media →
  локальные Vosk/Piper → Core, а `transcript.final` содержит
  `simulated=false`.

После проверки доступны:

- Web: <http://127.0.0.1:5173>;
- единый статус: <http://127.0.0.1:8099/status>;
- Core readiness: <http://127.0.0.1:8080/actuator/health/readiness>;
- AI readiness: <http://127.0.0.1:8090/ready>;
- Media readiness: <http://127.0.0.1:8091/ready>.

AI `/ready` возвращает 503, если настоящие речевые модели отсутствуют,
повреждены или заменены тестовой подменой. Карточный fallback при этом остаётся
доступен через `/health`, но полный стенд не будет считаться готовым.

## Повседневные операции

| Операция | Windows | Ubuntu |
|---|---|---|
| состояние | `.\scripts\stack.ps1 status` | `bash scripts/stack.sh status` |
| логи | `.\scripts\stack.ps1 logs` | `bash scripts/stack.sh logs` |
| restart без потери БД | `.\scripts\stack.ps1 restart` | `bash scripts/stack.sh restart` |
| остановка с сохранением БД | `.\scripts\stack.ps1 stop` | `bash scripts/stack.sh stop` |
| повторный smoke | `.\scripts\stack.ps1 smoke` | `bash scripts/stack.sh smoke` |

Для пакетного обновления сначала перенесите новый `images.tar`, затем:

```powershell
.\scripts\stack.ps1 update .\images.tar
```

```bash
bash scripts/stack.sh update ./images.tar
```

Команда загружает образы, снова выполняет `doctor` и пересоздаёт контейнеры,
сохраняя именованный том PostgreSQL.

Полный сброс данных нужен только для чистого испытательного развёртывания. Он
необратимо удаляет локальную БД:

```powershell
docker compose --env-file .env -f compose.yaml -f compose.offline.yaml down --volumes
```

На Ubuntu используется та же команда. Не выполняйте её на стенде с нужными
данными.

## Порты и доступ

| Порт | Протокол | Компонент | Публикация по умолчанию |
|---:|---|---|---|
| 5173 | TCP | Web | `127.0.0.1` |
| 8080 | TCP | Core | `127.0.0.1` |
| 8088 | TCP | Asterisk ARI | `127.0.0.1` |
| 8090 | TCP | AI | `127.0.0.1` |
| 8091 | TCP | Media | `127.0.0.1` |
| 8099 | TCP | Monitor | `127.0.0.1` |
| 8100 | TCP | локальный admin helper | `127.0.0.1` |
| 5432 | TCP | PostgreSQL | `127.0.0.1` |
| 5060 | TCP/UDP | SIP | `SIRENA_BIND_ADDRESS` |
| 10000-10100 | UDP | RTP | `SIRENA_BIND_ADDRESS` |

Все пароли и service tokens хранятся только в игнорируемом `.env` и передаются
контейнерам через переменные окружения. Образы и репозиторий не содержат
секретов. Локальный профиль использует HTTP только внутри хоста/compose-сети.
Публикация этого профиля в LAN и публичный интернет не поддерживаются. Для неё
нужен отдельный профиль с `CORE_AUTH_ENABLED=true`, Web, собранным с
`VITE_AUTH_MODE=secure`, и TLS reverse proxy; ключи и сертификаты должны
передаваться отдельными файлами/переменными и не попадать в репозиторий или
offline-bundle. `doctor` отклоняет любой не-loopback адрес, поэтому случайно
открыть demo-auth стенд наружу нельзя.

## Основные переменные

- `SIRENA_BIND_ADDRESS`, `*_PORT` — локальные адреса и порты;
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — PostgreSQL;
- `CORE_MEDIA_SERVICE_TOKEN`, `AI_SERVICE_TOKEN` — межсервисная авторизация;
- `AI_MODELS_DIR`, `AI_STT`, `AI_TTS`, `AI_REQUIRE_REAL_SPEECH` — локальные
  речевые модели и строгая readiness-проверка;
- `ASTERISK_*` — SIP, RTP, ARI и секреты локальной телефонии;
- `CORE_AUTH_ENABLED`, `CORE_BOOTSTRAP_ADMIN_*`, `VITE_AUTH_MODE` — доступ к UI.

Полный перечень и безопасные placeholder-значения находятся в `.env.example`.

## Диагностика

1. Выполните `doctor`; он ловит отсутствующий Docker Engine, образ, модель,
   небезопасный placeholder и занятый порт до старта.
2. Выполните `status`; поле `checks` покажет конкретный компонент `DOWN`.
3. Выполните `logs` и найдите первую ошибку соответствующего компонента.
4. После исправления выполните `restart`, затем `smoke`.

Частые случаи:

- `Отсутствует модель` — скопирован не весь `models/` либо повреждён пакет;
- `Docker-образ ... отсутствует` — повторите `docker load --input images.tar`;
- `TCP-порт ... уже занят` — остановите конфликтующий процесс или измените
  порт в `.env`;
- AI `not_ready` — проверьте пути и SHA-256 Vosk/Piper;
- Media `not ready` — проверьте ARI credentials и health Asterisk;
- нет внешнего SIP-аудио — проверьте `ASTERISK_EXTERNAL_ADDRESS`, UDP 5060 и
  диапазон RTP. Встроенный voice smoke не требует softphone.

## Подтверждённые платформы

28 сентября 2026 года весь стек, clean start, restart, карточный и настоящий
голосовой smoke проверены на Windows 11 Pro 10.0.26200 x86-64, Docker Desktop
4.81.0, Docker Engine 29.6.1 и Compose 5.2.0 (16 CPU, 8 ГБ памяти Docker).

Отдельного стенда Windows 10 и Ubuntu 20.04+ во время этой работы не было.
Скрипт Ubuntu и Compose-конфигурация подготовлены, но совместимость этих двух
целевых ОС не следует считать подтверждённой до выполнения на них раздела
«Запуск и проверка».
