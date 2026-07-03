# Sources Manifest — Wiki Язык 1С

## Source Policy

- Источники используются для синтеза и ссылок.
- Полные тексты официальной документации и книг не копируются в wiki-страницы.
- После явного подтверждения пользователя bounded raw-capture можно сохранять вне Nextcloud в runtime.
- Для защищенных источников нужен явный шаг подтверждения перед login/download.
- В wiki хранятся только source metadata, пути к runtime-файлам, размеры и checksum.

## Raw Storage

- Runtime raw root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/`
- Project manifest: `Wiki/1C-Language/raw/manifest.md`
- Runtime manifest for current captures: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/manifest.json`

## Sources

### karpathy-llm-wiki-2026-04-04

- Type: article / gist.
- URL: `https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f`
- Status: read.
- Role: architectural pattern for the wiki.
- Key idea: raw sources remain immutable; LLM maintains generated wiki pages and a schema/instructions file; operations include ingest, query, and lint.

### its-1c-v8327doc

- Type: official documentation.
- URL: `https://its.1c.ru/db/v8327doc`
- Platform version: `8.3.27`.
- Status: public structure inspected; authorized browser login probe succeeded.
- Encoding observed: `Windows-1251`.
- Base path observed: `/db/v8327doc/`.
- Access note: credentials must not be stored in this repo. Authorized access was verified via temporary headless Chromium session only.
- Auth probe: `ping.json=200`; personal access marker observed: access until `30.06.2028`.

Top-level sections observed:

- `Руководство разработчика`
- `Руководство администратора`
- `Клиент-серверный вариант. Руководство администратора`
- `Руководство пользователя`
- `Руководство пользователя. Интерфейс «Такси»`
- `V8Update`

Developer guide chapters observed:

- `Глава 1. Концепция системы`
- `Глава 2. Работа с конфигурацией`
- `Глава 3. Интерфейс приложения`
- `Глава 4. Встроенный язык`
- `Глава 5. Объекты конфигурации`
- `Глава 6. Командный интерфейс`
- `Глава 7. Формы`
- `Глава 8. Работа с запросами`
- `Глава 9. Работа с данными`
- `Глава 10. Система компоновки данных`
- `Глава 11. Бухгалтерский учет`
- `Глава 12. Периодические расчеты`
- `Глава 13. Бизнес-процессы и задачи`
- `Глава 14. Анализ данных и прогнозирование`
- `Глава 15. Механизмы обмена данными`
- `Глава 16. Работа с различными форматами данных`
- `Глава 17. Интеграция с внешними системами`
- `Глава 18. Дополнительные возможности веб-клиента`
- `Глава 19. Механизм заданий`
- `Глава 20. Механизм полнотекстового поиска в данных`
- `Глава 21. Механизм временного хранилища, работа с файлами и картинками`
- `Глава 22. Журнал регистрации`
- `Глава 23. Механизм криптографии`
- `Глава 24. Механизм разделения данных`
- `Глава 25. История данных`
- `Глава 26. Механизм копий базы данных`
- `Глава 27. Глобальный поиск`
- `Глава 28. Разработка для мобильных устройств`
- `Глава 29. Система взаимодействия`
- `Глава 30. Расширение конфигурации`
- `Глава 31. Отладка и тестирование прикладных решений`
- `Глава 32. Внешние компоненты`
- `Глава 33. Особенности разработки кроссплатформенных прикладных решений`
- `Глава 34. Прочие механизмы`
- `Глава 35. Инструменты разработки`
- `Глава 36. Механизм сравнения и объединения конфигураций`
- `Глава 37. Групповая разработка конфигурации`
- `Глава 38. Поставка и поддержка конфигурации`
- `Глава 39. Сервисные возможности`

Authorized content probe:

- `https://its.1c.ru/db/v8327doc/content/49/hdoc`
- Title observed: `Глава 4. Встроенный язык :: Руководство разработчика :: 1С:Предприятие 8.3.27. Документация`
- Text prefix observed only for structure verification, not stored as source content.

### its-1c-v8327doc-dev-intro

- Type: official documentation section.
- URL: `https://its.1c.ru/db/v8327doc/content/45/1`
- Iframe source: `/db/content/v8327doc/src/руководство разработчика/введение.htm`
- Status: ingested as structure and synthesized notes; full raw source captured.
- Full text stored: yes, outside Nextcloud runtime.
- Runtime HTML: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-introduction.html`
- Runtime text: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-introduction.txt`
- Captured at UTC: `2026-04-25T13:54:15+00:00`
- HTML sha256: `71a3e5dda326a725f0b8387a1540a0d0120656d9086ba547f396acd61d7015a9`
- Text sha256: `23b65e346ea0123551391f5524f3129dc95e57fe486c3b37a6718e56c86be9b7`
- Text chars: `21891`.

### its-1c-v8327doc-dev-chapter-1

- Type: official documentation section.
- URL: `https://its.1c.ru/db/v8327doc/content/46/1`
- Iframe source: `/db/content/v8327doc/src/руководство разработчика/глава 1. концепция системы.htm`
- Status: ingested as structure and synthesized notes; full raw source captured.
- Full text stored: yes, outside Nextcloud runtime.
- Runtime HTML: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-chapter-1-concept-system.html`
- Runtime text: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/developer-guide-chapter-1-concept-system.txt`
- Captured at UTC: `2026-04-25T13:54:15+00:00`
- HTML sha256: `2ca001ecc4c75e16d342c128827cad00d5987fcae047af7c5c3ba834893b8fee`
- Text sha256: `35a49490db1bee4a50f0da614d6f85b5b7e4b727eed8ab74958f5257696dd22d`
- Text chars: `62684`.

### its-1c-v8327doc-dev-chapters-2-11

- Type: official documentation sections.
- Scope: `Руководство разработчика`, chapters 2-11.
- Status: full raw source captured outside Nextcloud runtime; not synthesized yet.
- Capture timestamp UTC: `2026-04-25T14:13:41+00:00`.
- Request pacing: sequential capture with `10-18` second pauses between chapter requests.
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/`
- Detailed file metadata: `Wiki/1C-Language/raw/manifest.md`.

Captured sections:

| Source id | Title | Page URL | Slug | Text chars |
|---|---|---|---|---:|
| `its-1c-v8327doc-dev-chapter-2` | `Глава 2. Работа с конфигурацией` | `https://its.1c.ru/db/v8327doc/content/47/1` | `developer-guide-chapter-2-configuration-work` | `103741` |
| `its-1c-v8327doc-dev-chapter-3` | `Глава 3. Интерфейс приложения` | `https://its.1c.ru/db/v8327doc/content/48/1` | `developer-guide-chapter-3-application-interface` | `73040` |
| `its-1c-v8327doc-dev-chapter-4` | `Глава 4. Встроенный язык` | `https://its.1c.ru/db/v8327doc/content/49/1` | `developer-guide-chapter-4-built-in-language` | `165910` |
| `its-1c-v8327doc-dev-chapter-5` | `Глава 5. Объекты конфигурации` | `https://its.1c.ru/db/v8327doc/content/50/1` | `developer-guide-chapter-5-configuration-objects` | `571671` |
| `its-1c-v8327doc-dev-chapter-6` | `Глава 6. Командный интерфейс` | `https://its.1c.ru/db/v8327doc/content/51/1` | `developer-guide-chapter-6-command-interface` | `83913` |
| `its-1c-v8327doc-dev-chapter-7` | `Глава 7. Формы` | `https://its.1c.ru/db/v8327doc/content/52/1` | `developer-guide-chapter-7-forms` | `494370` |
| `its-1c-v8327doc-dev-chapter-8` | `Глава 8. Работа с запросами` | `https://its.1c.ru/db/v8327doc/content/53/1` | `developer-guide-chapter-8-queries` | `148198` |
| `its-1c-v8327doc-dev-chapter-9` | `Глава 9. Работа с данными` | `https://its.1c.ru/db/v8327doc/content/54/1` | `developer-guide-chapter-9-data-work` | `75074` |
| `its-1c-v8327doc-dev-chapter-10` | `Глава 10. Система компоновки данных` | `https://its.1c.ru/db/v8327doc/content/55/1` | `developer-guide-chapter-10-data-composition-system` | `219874` |
| `its-1c-v8327doc-dev-chapter-11` | `Глава 11. Бухгалтерский учет` | `https://its.1c.ru/db/v8327doc/content/56/1` | `developer-guide-chapter-11-accounting` | `26683` |

### its-1c-v8327doc-dev-chapters-12-39

- Type: official documentation sections.
- Scope: `Руководство разработчика`, chapters 12-39.
- Status: full raw source captured outside Nextcloud runtime; not synthesized yet.
- Capture timestamp UTC: `2026-04-26T05:49:36Z` - `2026-04-26T05:56:06Z`.
- Request pacing: sequential capture with `10-18` second pauses between chapter requests.
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-v8327doc/developer-guide/`
- Detailed file metadata: `Wiki/1C-Language/raw/manifest.md`.

Captured sections:

| Source id | Title | Page URL | Slug | Text chars |
|---|---|---|---|---:|
| `its-1c-v8327doc-dev-chapter-12` | `Глава 12. Периодические расчеты` | `https://its.1c.ru/db/v8327doc/content/57/1` | `developer-guide-chapter-12-periodic-calculations` | `18350` |
| `its-1c-v8327doc-dev-chapter-13` | `Глава 13. Бизнес-процессы и задачи` | `https://its.1c.ru/db/v8327doc/content/58/1` | `developer-guide-chapter-13-business-processes-and-tasks` | `40415` |
| `its-1c-v8327doc-dev-chapter-14` | `Глава 14. Анализ данных и прогнозирование` | `https://its.1c.ru/db/v8327doc/content/59/1` | `developer-guide-chapter-14-data-analysis-and-forecasting` | `48256` |
| `its-1c-v8327doc-dev-chapter-15` | `Глава 15. Механизмы обмена данными` | `https://its.1c.ru/db/v8327doc/content/60/1` | `developer-guide-chapter-15-data-exchange-mechanisms` | `120706` |
| `its-1c-v8327doc-dev-chapter-16` | `Глава 16. Работа с различными форматами данных` | `https://its.1c.ru/db/v8327doc/content/61/1` | `developer-guide-chapter-16-data-formats` | `251671` |
| `its-1c-v8327doc-dev-chapter-17` | `Глава 17. Интеграция с внешними системами` | `https://its.1c.ru/db/v8327doc/content/62/1` | `developer-guide-chapter-17-external-systems-integration` | `297012` |
| `its-1c-v8327doc-dev-chapter-18` | `Глава 18. Дополнительные возможности веб-клиента` | `https://its.1c.ru/db/v8327doc/content/63/1` | `developer-guide-chapter-18-web-client-extra-features` | `22913` |
| `its-1c-v8327doc-dev-chapter-19` | `Глава 19. Механизм заданий` | `https://its.1c.ru/db/v8327doc/content/64/1` | `developer-guide-chapter-19-jobs-mechanism` | `30285` |
| `its-1c-v8327doc-dev-chapter-20` | `Глава 20. Механизм полнотекстового поиска в данных` | `https://its.1c.ru/db/v8327doc/content/65/1` | `developer-guide-chapter-20-full-text-search` | `28061` |
| `its-1c-v8327doc-dev-chapter-21` | `Глава 21. Механизм временного хранилища, работа с файлами и картинками` | `https://its.1c.ru/db/v8327doc/content/66/1` | `developer-guide-chapter-21-temporary-storage-files-and-pictures` | `41515` |
| `its-1c-v8327doc-dev-chapter-22` | `Глава 22. Журнал регистрации` | `https://its.1c.ru/db/v8327doc/content/67/1` | `developer-guide-chapter-22-event-log` | `35258` |
| `its-1c-v8327doc-dev-chapter-23` | `Глава 23. Механизм криптографии` | `https://its.1c.ru/db/v8327doc/content/68/1` | `developer-guide-chapter-23-cryptography` | `38960` |
| `its-1c-v8327doc-dev-chapter-24` | `Глава 24. Механизм разделения данных` | `https://its.1c.ru/db/v8327doc/content/69/1` | `developer-guide-chapter-24-data-separation` | `48349` |
| `its-1c-v8327doc-dev-chapter-25` | `Глава 25. История данных` | `https://its.1c.ru/db/v8327doc/content/70/1` | `developer-guide-chapter-25-data-history` | `40998` |
| `its-1c-v8327doc-dev-chapter-26` | `Глава 26. Механизм копий базы данных` | `https://its.1c.ru/db/v8327doc/content/71/1` | `developer-guide-chapter-26-database-copies` | `45485` |
| `its-1c-v8327doc-dev-chapter-27` | `Глава 27. Глобальный поиск` | `https://its.1c.ru/db/v8327doc/content/72/1` | `developer-guide-chapter-27-global-search` | `31719` |
| `its-1c-v8327doc-dev-chapter-28` | `Глава 28. Разработка для мобильных устройств` | `https://its.1c.ru/db/v8327doc/content/73/1` | `developer-guide-chapter-28-mobile-development` | `581173` |
| `its-1c-v8327doc-dev-chapter-29` | `Глава 29. Система взаимодействия` | `https://its.1c.ru/db/v8327doc/content/74/1` | `developer-guide-chapter-29-collaboration-system` | `208287` |
| `its-1c-v8327doc-dev-chapter-30` | `Глава 30. Расширение конфигурации` | `https://its.1c.ru/db/v8327doc/content/75/1` | `developer-guide-chapter-30-configuration-extensions` | `128576` |
| `its-1c-v8327doc-dev-chapter-31` | `Глава 31. Отладка и тестирование прикладных решений` | `https://its.1c.ru/db/v8327doc/content/76/1` | `developer-guide-chapter-31-debugging-and-testing` | `186308` |
| `its-1c-v8327doc-dev-chapter-32` | `Глава 32. Внешние компоненты` | `https://its.1c.ru/db/v8327doc/content/77/1` | `developer-guide-chapter-32-external-components` | `25566` |
| `its-1c-v8327doc-dev-chapter-33` | `Глава 33. Особенности разработки кроссплатформенных прикладных решений` | `https://its.1c.ru/db/v8327doc/content/78/1` | `developer-guide-chapter-33-cross-platform-development` | `7096` |
| `its-1c-v8327doc-dev-chapter-34` | `Глава 34. Прочие механизмы` | `https://its.1c.ru/db/v8327doc/content/79/1` | `developer-guide-chapter-34-other-mechanisms` | `101381` |
| `its-1c-v8327doc-dev-chapter-35` | `Глава 35. Инструменты разработки` | `https://its.1c.ru/db/v8327doc/content/80/1` | `developer-guide-chapter-35-development-tools` | `203849` |
| `its-1c-v8327doc-dev-chapter-36` | `Глава 36. Механизм сравнения и объединения конфигураций` | `https://its.1c.ru/db/v8327doc/content/81/1` | `developer-guide-chapter-36-configuration-compare-and-merge` | `46432` |
| `its-1c-v8327doc-dev-chapter-37` | `Глава 37. Групповая разработка конфигурации` | `https://its.1c.ru/db/v8327doc/content/82/1` | `developer-guide-chapter-37-group-development` | `63850` |
| `its-1c-v8327doc-dev-chapter-38` | `Глава 38. Поставка и поддержка конфигурации` | `https://its.1c.ru/db/v8327doc/content/83/1` | `developer-guide-chapter-38-delivery-and-support` | `40912` |
| `its-1c-v8327doc-dev-chapter-39` | `Глава 39. Сервисные возможности` | `https://its.1c.ru/db/v8327doc/content/84/1` | `developer-guide-chapter-39-service-features` | `92873` |

### its-1c-metod8dev-developers

- Type: official methodology knowledge base.
- URL: `https://its.1c.ru/db/metod8dev#browse:13:-1:3199`
- Scope: `Методическая поддержка для разработчиков и администраторов 1С:Предприятия 8` -> `Разработчикам`.
- Status: full raw source captured outside Nextcloud runtime; not synthesized yet.
- Capture completed UTC: `2026-04-26T06:41:50Z`.
- Runtime source root: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-metod8dev/developers/`
- Runtime manifest: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-metod8dev/developers/manifest.json`
- Structure summary: `73` folders, `601` unique documents, `0` failures.
- Text chars total: `7392171`.
- Detailed structure summary: `Wiki/1C-Language/sources/metod8dev-developers-structure.md`.

Top-level captured branches:

| Branch | Browse path | Subfolders | Documents |
|---|---|---:|---:|
| `Платформа, механизмы и технологии` | `/db/metod8dev/browse/13/-1/3199/3224` | `33` | `377` |
| `Дополнительные средства разработки: библиотеки, обработки, руководства` | `/db/metod8dev/browse/13/-1/3199/3200` | `9` | `71` |
| `Универсальные механизмы в типовых конфигурациях (режим обычного приложения)` | `/db/metod8dev/browse/13/-1/3199/3271` | `0` | `4` |
| `Технологические вопросы крупных внедрений` | `/db/metod8dev/browse/13/-1/3199/3258` | `11` | `89` |
| `Обмен данными, прикладные технологии` | `/db/metod8dev/browse/13/-1/3199/3210` | `11` | `30` |
| `"1С:Документооборот" для разработчика` | `/db/metod8dev/browse/13/-1/3199/3223` | `0` | `25` |
| `Диагностика и исправление проблем` | `/db/metod8dev/browse/13/-1/3199/3222` | `0` | `2` |
| `Работа с торговым оборудованием` | `/db/metod8dev/browse/13/-1/3199/3270` | `0` | `3` |
