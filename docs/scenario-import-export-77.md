# Ручной импорт и экспорт (#77)

Core принимает пакет `{"scenarios":[...]}` через `POST
/api/teacher/scenarios/import/validate` (проверка без записи) и `POST
/api/teacher/scenarios/import` (добавить всё или ничего). Импорт выключен по
умолчанию. Для локального демо запустите Core с
`CORE_SCENARIO_IMPORT_ENABLED=true` и обращайтесь напрямую к `127.0.0.1:8080`.
Удалённые запросы получают 403 даже при включённой настройке. До RBAC нельзя
публиковать этот API во внешней сети или считать его многопользовательским.
В Docker запрос с хоста к опубликованному порту не считается loopback внутри
контейнера. Для такого демо включите переменную в `docker compose` и отправляйте
пакет через `docker compose exec -T core curl ...` внутри контейнера; пример
автоматического прогона — `scripts/smoke_import_postgres.py`.

Каждый элемент проверяется по `contracts/scenario.schema.json` (только новый
`groundTruthV2`), десериализуется в модель Core, сравнивается с текущей версией
официального классификатора и повторно рассчитывается Core по `expectedInput`.
Код, тип происшествия, сценарий реагирования и наборы служб должны совпасть;
названия/причины маршрутизации записываются из каталога Core. Каталог импортом
не меняется. Пакет ограничен 25 сценариями и 2 МБ. Дубликаты id внутри пакета
или в хранилище не перезаписываются. Проверку нужно выполнить до применения;
само применение валидирует пакет заново на случай изменений между запросами.

Для проверки вручную создайте `package.json` с новым UUID сценария и действующим
эталоном, например на основе `contracts/examples/scenario-1050602.json`:

```powershell
$package = Get-Content package.json -Raw -Encoding UTF8
Invoke-RestMethod http://127.0.0.1:8080/api/teacher/scenarios/import/validate -Method Post -ContentType 'application/json; charset=utf-8' -Body $package
Invoke-RestMethod http://127.0.0.1:8080/api/teacher/scenarios/import -Method Post -ContentType 'application/json; charset=utf-8' -Body $package
Invoke-RestMethod http://127.0.0.1:8080/api/teacher/scenarios
```

После оценки карточного занятия его сохранённый отчёт можно скачать без
внешнего сервиса. Подставьте настоящий id оценённой сессии:

```powershell
$sessionId = '<UUID оценённой сессии>'
Invoke-WebRequest "http://127.0.0.1:8080/api/teacher/sessions/$sessionId/report.xlsx" -OutFile report.xlsx
Invoke-WebRequest "http://127.0.0.1:8080/api/teacher/sessions/$sessionId/report.pdf" -OutFile report.pdf
Invoke-WebRequest http://127.0.0.1:8080/api/teacher/analytics/summary.xlsx -OutFile summary.xlsx
Invoke-WebRequest http://127.0.0.1:8080/api/teacher/analytics/summary.pdf -OutFile summary.pdf
```

Каждый формат строится из одного снимка сохранённого отчёта или агрегата на
момент запроса. В персональном отчёте есть id сессии, версия и код
классификатора, балл, результаты критериев и **коды** ошибок. Свободные тексты
ошибок, рекомендации, карточка, адрес, телефон и транскрипт не выгружаются.
Сводка содержит версию текущего каталога и агрегаты, без id отдельных занятий. Незавершённая
карточка не экспортируется; отчёт `SCORED` без сохранённого `SessionReport`
получает 404. PDF использует Unicode TTF; Docker-образ Core содержит DejaVu,
а для иной ОС путь можно задать через `CORE_EXPORT_FONT_PATH`.

При `CORE_STORAGE=postgres` импортированные сценарии и отчёты переживают
рестарт; при `in-memory` данные остаются временными. Экспортные URL также
нельзя выводить наружу без RBAC/защищённого шлюза: хотя тела файлов
обезличены, id занятия и балл относятся к внутренним учебным данным.
