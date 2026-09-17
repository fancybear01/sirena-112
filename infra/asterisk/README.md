# Asterisk (локальный SIP-контур)

Минимальный Asterisk для задачи [#9](https://github.com/fancybear01/sirena-112/issues/9):

- два внутренних SIP-номера: **1001** и **1002**;
- **ARI** на HTTP `:8088` и отдельный пользователь (по умолчанию `media`);
- кодеки **μ-law / A-law** (RTP), совместимые с последующим Media Gateway;
- внутренний dialplan `from-internal` для звонков `_10XX`.

Секреты не хранятся в git: при старте контейнера `docker-entrypoint.sh` собирает
`ari.conf` и `pjsip.endpoints.conf` из шаблонов и переменных окружения.
Примеры без реальных паролей: `templates/*.example`, `infra/asterisk/.env.example`.

## Быстрый старт

1. В корне репозитория скопируйте `.env.example` в `.env` (если ещё не сделали).
2. При необходимости задайте пароли и `ASTERISK_EXTERNAL_ADDRESS` (см. ниже).
3. Запустите Asterisk:

```bash
docker compose up -d --build asterisk
docker compose logs -f asterisk
```

4. Дождитесь строки в логах о готовности PJSIP/HTTP (или успешного healthcheck).

## Проверка ARI

Подставьте пользователя и пароль из `.env` (`ASTERISK_ARI_USER` / `ASTERISK_ARI_PASSWORD`):

```bash
curl -sS -u "media:change-me-ari" \
  "http://127.0.0.1:${ASTERISK_HTTP_PORT:-8088}/ari/asterisk/info" | head
```

Ожидается JSON с полем `build` / `system`.

Swagger ARI (если включён в образе):

```bash
open "http://127.0.0.1:${ASTERISK_HTTP_PORT:-8088}/ari/api-docs/resources.json"
```

## Регистрация SIP-клиента

Подойдёт любой softphone (Zoiper, Linphone, MicroSIP и т.д.).

| Параметр   | Значение                          |
|-----------|-----------------------------------|
| Сервер    | `127.0.0.1`                       |
| Порт      | `5060` (UDP)                      |
| Логин     | `1001` или `1002`                 |
| Пароль    | из `.env`: `ASTERISK_SIP_1001_PASSWORD` / `1002` |
| Transport | UDP                               |

После регистрации в CLI Asterisk (опционально):

```bash
docker compose exec asterisk asterisk -rx "pjsip show endpoints"
```

У нужного endpoint должно быть `Contact:` с вашим клиентом.

## Тестовый внутренний звонок

1. Зарегистрируйте **1001** на одном softphone (или на одном аккаунте).
2. Зарегистрируйте **1002** на втором (или второй вкладке/устройстве).
3. С **1001** наберите **1002** (и наоборот).

Dialplan: контекст `from-internal`, шаблон `_10XX` → `Dial(PJSIP/${EXTEN})`.
При успехе слышен ответ и короткое demo-аудио после `Answer()` на отдельных
номерах; между двумя зарегистрированными абонентами — обычный двусторонний разговор.

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `ASTERISK_SIP_PORT` | SIP signaling (UDP/TCP) на хосте |
| `ASTERISK_HTTP_PORT` | HTTP + ARI |
| `ASTERISK_RTP_PORT_START` / `END` | диапазон RTP на хосте |
| `ASTERISK_EXTERNAL_ADDRESS` | IP, который softphone использует для RTP (часто `127.0.0.1`) |
| `ASTERISK_SIP_1001_PASSWORD` / `1002` | пароли SIP |
| `ASTERISK_ARI_USER` / `PASSWORD` | учётная запись ARI |

Полный список placeholder-значений: [`infra/asterisk/.env.example`](.env.example).

## Troubleshooting

**Клиент не регистрируется**

- Проверьте порт `5060/udp` и пароль из `.env`.
- Убедитесь, что контейнер запущен: `docker compose ps asterisk`.

**Нет аудио / односторонняя связь**

- На macOS/Windows для RTP часто нужен `ASTERISK_EXTERNAL_ADDRESS=127.0.0.1`
  (или LAN-IP машины, если softphone на другом устройстве в сети).
- Откройте проброс UDP `10000-10100` (задаётся в `compose.yaml`).

**ARI 401 / connection refused**

- Сверьте `ASTERISK_ARI_USER` и `ASTERISK_ARI_PASSWORD` с тем, что передаётся в curl.
- Проверьте `ASTERISK_HTTP_PORT` и `docker compose logs asterisk`.

## Дальше (Media Gateway)

Go `services/media` подключается к этому Asterisk по ARI и RTP; конфигурация
телефонии остаётся здесь, в `infra/asterisk`, а не внутри Media-сервиса.

Контрольная точка после #9:

1. Asterisk up, ARI отвечает.
2. SIP 1001/1002 зарегистрированы, внутренний звонок проходит в обе стороны.
3. Второй разработчик повторяет шаги только по этому README и `.env.example`.
