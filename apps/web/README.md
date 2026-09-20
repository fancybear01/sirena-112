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
| `VITE_API_BASE_URL` | URL Core API без обязательного завершающего `/` | В API-режиме — текущий origin (Vite proxy); в mock — `http://localhost:8080` |

Mock-режим не требует backend:

```powershell
$env:VITE_API_MODE = 'mock'
npm --prefix apps/web run dev
```

Подключение Kotlin Core API:

```powershell
$env:VITE_API_MODE = 'api'
npm --prefix apps/web run dev
```

В режиме `api` Vite проксирует `/api` и `/ws` на Core (`127.0.0.1:8080`),
поэтому браузеру не нужен CORS. Для размещения Web отдельно от Core задайте
`VITE_API_BASE_URL` или настройте такие же маршруты на обратном прокси.
После изменения переменных перезапустите Vite: он считывает `VITE_*` при старте.
Файл `.env` не обязателен.

## Архитектура интеграции

- `src/api/types.ts` — общие модели `Scenario`, `Session`, `OperatorCardInput`,
  `CardCalculation`, динамической формы и
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

Student flow следует контракту карточки 0.3:

- `GET .../card-form` возвращает доступные уровни признаков и зависимые вопросы;
- `PATCH .../card` и `POST .../submit` получают только `{ input, expectedRevision }`;
- `incidentType`, код классификатора и службы берутся только из
  `card.calculation` и показываются без возможности редактирования;
- адрес хранит обязательный `displayAddress` и отдельные структурированные поля,
  без внешнего геокодинга;
- `startedAt`, `endedAt`, `timeLimitSeconds` и `timeLimitExceeded` используются
  для фактической длительности и явного отображения превышения.

Core реализует описанный в OpenAPI `GET /api/student/assignments` и возвращает
активные или уже оценённые карточные сессии. При `404` HTTP-адаптер сохраняет
совместимость со старыми стендами: восстанавливает id запущенной teacher-сессии
из локального кэша и запрашивает состояние через `GET /api/student/sessions/{id}`.
Fallback изолирован в адаптере и не попадает в UI.

Остальные известные пробелы изолированы аналогично:

- Статус готовности сценария отсутствует в `Scenario`; HTTP-адаптер считает
  полученные от teacher endpoint сценарии готовыми. Mock дополнительно показывает
  черновик.
- Teacher endpoint для поиска текущей сессии отсутствует; HTTP-клиент
  сохраняет id последней созданной сессии локально до «Нового занятия»,
  а после перезагрузки и каждые 3 секунды получает её актуальное состояние
  от Core. Состояние не восстанавливается в новом браузере без локального id.

Изменять общие контракты для этих уточнений следует отдельно, после согласования.

## Проверка полного mock-пути

1. Откройте `/teacher`, выберите сценарий «Задымление в мусоропроводе»
   (`1050602`) и нажмите «Запустить занятие».
2. Перейдите на `/student`: mock-клиент подхватит ту же сессию и сценарий.
3. Последовательно выберите «Жилой дом → Мусоропровод → Дым». Ответьте на
   появившиеся вопросы, заполните адрес и сведения о пострадавших.
4. Убедитесь, что тип и службы появились в read-only блоке Core, дождитесь
   статуса сохранения и отправьте карточку на оценку.
5. Проверьте итоговый отчёт с фактической длительностью, баллами, ошибками и
   рекомендациями.
6. Вернитесь на `/teacher` и завершите занятие при необходимости.

Mock-сессия, черновик и отчёт сохраняются в `localStorage`. Запуск нового занятия
очищает предыдущий student draft. Интеграционный тест `src/features/mockFlow.test.tsx`
проверяет связь teacher → student → report.

## Скриншоты демонстрации

1. [Выбор сценария](docs/screenshots/01-teacher-scenarios.png)
2. [Активная сессия преподавателя](docs/screenshots/02-teacher-active-session.png)
3. [Пошаговая карточка и расчёт Core](docs/screenshots/03-student-card.png)
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
