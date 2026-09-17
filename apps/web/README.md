# Web

Frontend Сирены-112 на React, TypeScript, Vite, React Router и Mantine. По
умолчанию он работает без backend, но экраны уже используют интерфейсы API и не
зависят от конкретного транспорта.

## Установка и запуск

Нужны Node.js 20.19+ и npm. Из корня репозитория:

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
```

Откройте `http://localhost:5173/login`. Vite поддерживает прямой вход и обновление
SPA-маршрутов `/admin`, `/teacher` и `/student`. На другом web-сервере потребуется
аналогичный fallback на `index.html`.

## Режимы API

Режим задаётся при запуске через переменные окружения:

| Переменная | Значения | По умолчанию |
| --- | --- | --- |
| `VITE_API_MODE` | `mock` или `api` | `mock` |
| `VITE_API_BASE_URL` | URL Core API без обязательного завершающего `/` | `http://localhost:8080` |

Mock-режим не требует backend:

```powershell
$env:VITE_API_MODE = 'mock'
npm --prefix apps/web run dev
```

Подключение Kotlin Core API:

```powershell
$env:VITE_API_MODE = 'api'
$env:VITE_API_BASE_URL = 'http://localhost:8080'
npm --prefix apps/web run dev
```

После изменения переменных перезапустите Vite: он считывает `VITE_*` при старте.
Файл `.env` не обязателен.

## Архитектура интеграции

- `src/api/types.ts` — общие модели `Scenario`, `Session`, `OperatorCard` и
  `SessionReport`, сверенные с `contracts/openapi.yaml` и
  `contracts/scenario.schema.json`.
- `src/api/httpClient.ts` — единый JSON transport, base URL, cookies и перевод
  сетевых/HTTP-сбоев в `ApiError`.
- `src/api/errors.ts` — единое отображение API-ошибок для экранов.
- `src/api/config.ts` — выбор `mock`/`api` и базового URL.
- `src/features/*/api/*Api.ts` — runtime-переключатели реализаций.
- `src/features/*/api/*HttpApi.ts` — адаптеры маршрутов Core API.
- `src/features/*/api/*MockApi.ts` — автономные реализации с теми же интерфейсами.

React-компоненты получают `TeacherApi` или `StudentApi`; для замены транспорта
или уточнения wire-формата менять экраны не нужно.

## Соответствие контрактам

Fixture-сценарии используют коды `category`, обязательные `groundTruth` и
`rubric.criteria` из `scenario.schema.json`. Общие session/report-модели вынесены
из feature-компонентов и соответствуют схемам OpenAPI.

В текущих контрактах остаются пробелы, которые клиент изолирует в адаптерах:

- `GET /api/student/assignments` не описывает response schema; клиент принимает
  один объект `{ scenario, session }` или массив таких объектов и выбирает первый.
- Для `PATCH .../card` и `POST .../submit` не описаны request body; сейчас клиент
  отправляет `OperatorCard` как JSON.
- `Session` не описывает `startedAt`/`endedAt`; клиент использует значения ответа,
  а при отсутствии `startedAt` запускает таймер локально.
- Статус готовности сценария отсутствует в `Scenario`; HTTP-адаптер считает
  полученные от teacher endpoint сценарии готовыми. Mock дополнительно показывает
  черновик.
- Teacher endpoint для восстановления текущей сессии отсутствует; HTTP-клиент
  сохраняет последнюю созданную сессию локально до «Нового занятия».

Изменять общие контракты для этих уточнений следует отдельно, после согласования.

## Проверка полного mock-пути

1. Откройте `/teacher`, выберите готовый сценарий и нажмите «Запустить занятие».
2. Перейдите на `/student`: mock-клиент подхватит ту же сессию и сценарий.
3. Заполните карточку, дождитесь статуса сохранения и отправьте её на оценку.
4. Проверьте итоговый отчёт с баллами, ошибками и рекомендациями.
5. Вернитесь на `/teacher` и завершите занятие при необходимости.

Mock-сессия, черновик и отчёт сохраняются в `localStorage`. Запуск нового занятия
очищает предыдущий student draft. Интеграционный тест `src/features/mockFlow.test.tsx`
проверяет связь teacher → student → report.

## Скриншоты демонстрации

1. [Выбор сценария](docs/screenshots/01-teacher-scenarios.png)
2. [Активная сессия преподавателя](docs/screenshots/02-teacher-active-session.png)
3. [Заполненная карточка обучающегося](docs/screenshots/03-student-card.png)
4. [Итоговый отчёт](docs/screenshots/04-student-report.png)

## Проверки

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run preview
```

`build` создаёт `apps/web/dist`, а `preview` локально проверяет собранную версию.
Вход пока демонстрационный: выбор роли только перенаправляет на нужный маршрут;
JWT и защита маршрутов не входят в текущую mock-интеграцию.
