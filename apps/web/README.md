# Web

Frontend-каркас Сирены-112 на React, TypeScript, Vite, React Router и Mantine.
Разделы ролей находятся в `src/features/admin`, `src/features/teacher` и
`src/features/student`; общие layout и заглушки — в `src/layout` и `src/shared`.

## Установка и запуск

Нужны Node.js 20.19+ и npm. Из корня репозитория один раз установите зависимости:

```bash
npm --prefix apps/web install
```

Затем запустите приложение одной командой:

```bash
npm --prefix apps/web run dev
```

Откройте `http://localhost:5173/login`. Vite обслуживает SPA-маршруты с возвратом
`index.html`: прямой вход и обновление `/admin`, `/teacher`, `/student` работают
в локальном dev-сервере. При публикации на другом сервере нужен аналогичный
fallback для неизвестных путей.

## Проверка маршрутов

1. На `/login` нажмите карточку администратора, преподавателя или обучающегося.
   Адрес должен смениться на `/admin`, `/teacher` или `/student` соответственно.
2. Обновите страницу в каждом разделе и откройте эти адреса напрямую.
3. Откройте произвольный адрес, например `/unknown`, чтобы увидеть страницу 404.
Вход пока демонстрационный: выбор роли только перенаправляет на нужный маршрут.
Защиты маршрутов, JWT и запросов к Core API нет.

Общие заглушки `LoadingState`, `ErrorState` и `EmptyState` доступны в
`src/shared/StatePlaceholder.tsx` для использования в разделах ролей.

## Команды

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run preview
```

`build` создаёт `apps/web/dist`, а `preview` локально проверяет собранную версию.
