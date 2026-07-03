# Log — Wiki Язык 1С

## [2026-04-25] bootstrap | Wiki structure

- Создан локальный wiki-контур по паттерну LLM-maintained wiki.
- Источник идеи: Karpathy `LLM Wiki`.
- Проверена публичная структура ITS 1C documentation v8.3.27 без логина и без скачивания данных.
- Зафиксировано, что использование логина ITS требует отдельного подтверждения.

## [2026-04-25] ingest | Developer guide introduction and chapter 1

- Составлена структура `Руководства разработчика` 8.3.27.
- Добавлены source notes по `Введению` и `Главе 1. Концепция системы`.
- Добавлены первые синтезированные wiki-страницы:
  - `pages/platform/developer-guide-introduction.md`;
  - `pages/platform/system-concept.md`;
  - `pages/platform/runtime-variants.md`;
  - `pages/concepts/configuration.md`;
  - `pages/concepts/configuration-object.md`;
  - `pages/runtime/development-and-execution.md`.
- Полные тексты официальной документации не сохранялись.

## [2026-04-25] raw-capture | Developer guide introduction and chapter 1

- По указанию пользователя включен raw-source слой для wiki.
- Полные HTML/TXT исходники `Введения` и `Главы 1. Концепция системы` сохранены вне Nextcloud в WorkAssistant runtime.
- В проект добавлены только metadata, локальные пути, размеры и SHA256:
  - `raw/manifest.md`;
  - `sources/manifest.md`.
- Учетные данные, cookies и session-state не сохранялись.

## [2026-04-25] raw-capture | Developer guide chapters 2-11

- Сохранены следующие 10 глав `Руководства разработчика` 8.3.27: главы 2-11.
- Захват выполнен в одном авторизованном headless Chromium session.
- Между запросами глав выдерживались паузы `10-18` секунд.
- Полные HTML/TXT исходники сохранены вне Nextcloud в runtime.
- В wiki обновлены только манифесты, пути, размеры и SHA256.
- Синтезированные страницы по этим главам пока не создавались.

## [2026-04-25] ingest | Developer guide chapters 2-11 overview pages

- Создан первый синтетический wiki-слой по главам 2-11.
- Добавлены обзорные страницы:
  - `pages/platform/configuration-work.md`;
  - `pages/platform/application-interface.md`;
  - `pages/syntax/built-in-language.md`;
  - `pages/concepts/configuration-objects-overview.md`;
  - `pages/platform/command-interface.md`;
  - `pages/platform/forms.md`;
  - `pages/query-language/queries.md`;
  - `pages/runtime/data-work.md`;
  - `pages/platform/data-composition-system.md`;
  - `pages/platform/accounting.md`.
- Страницы являются навигационными и синтезированными; полный текст источников в них не переносился.
- Следующий шаг: глубокое дробление приоритетных тем, начиная с `Глава 4. Встроенный язык`.

## [2026-04-25] ingest | Deep split of chapter 4 built-in language

- Выполнено глубокое разложение `Глава 4. Встроенный язык`.
- Добавлены отдельные страницы:
  - `pages/syntax/program-modules.md`;
  - `pages/syntax/module-contexts.md`;
  - `pages/syntax/module-types.md`;
  - `pages/syntax/module-format.md`;
  - `pages/syntax/data-types-and-values.md`;
  - `pages/syntax/expressions-and-operations.md`;
  - `pages/syntax/operators-and-control-flow.md`;
  - `pages/syntax/procedures-and-functions.md`;
  - `pages/syntax/exceptions.md`;
  - `pages/syntax/common-work-techniques.md`;
  - `pages/syntax/sync-async-methods.md`;
  - `pages/syntax/preprocessor-and-compilation-directives.md`.
- `pages/syntax/built-in-language.md` превращена в hub-страницу главы 4.
- Полный текст источника не копировался в wiki; страницы являются синтезированным слоем.

## [2026-04-25] ingest | Deep split of remaining loaded chapters

- Выполнен второй deep-split по оставшимся загруженным главам `Руководства разработчика` 8.3.27: главы 2, 3, 5, 6, 7, 8, 9, 10 и 11.
- Добавлены тематические страницы по блокам:
  - конфигурация и реструктуризация;
  - интерфейс приложения и `Такси`;
  - подсистемы, общие модули, роли и командная модель;
  - справочники, документы, регистры, отчеты/обработки, планы обмена, бизнес-процессы;
  - формы, данные формы, динамический список, элементы и события;
  - запросы, источники, соединения, временные таблицы, параметры и результат;
  - транзакции, блокировки, управляемые блокировки, индексы и динамические выборки;
  - СКД, наборы данных, настройки и вывод;
  - бухгалтерская модель, планы счетов и регистры бухгалтерии.
- Обновлены hub-страницы глав и главный `index.md`.
- Полный текст источников не копировался в wiki; страницы являются синтезированным слоем.

## [2026-04-25] tooling | Static HTML viewer

- Добавлен локальный self-contained просмотрщик `viewer.html`.
- Добавлен генератор `tools/build_viewer.py`.
- Просмотрщик собирает все Markdown-страницы wiki в один HTML-файл с навигацией, поиском и базовым Markdown-rendering.
- Внешние CDN, сервер и runtime raw-исходники не используются.

## [2026-04-25] quality | Answer-ready process sprint 1

- Добавлена политика качества `quality.md`.
- Добавлены `sources/coverage-map.md` и `sources/control-questions.md`.
- Введены статусы `raw-only`, `overview`, `answer-ready`, `verified`.
- Создана первая `answer-ready` страница: `pages/syntax/cycles.md`.
- `operators-and-control-flow.md`, `built-in-language.md` и `index.md` связаны с новой страницей.
- Цель процесса: практические вопросы должны закрываться wiki-страницами без обращения к raw-исходнику.

## [2026-04-26] raw-capture | Developer guide chapters 12-39

- Сохранены оставшиеся 28 глав `Руководства разработчика` 8.3.27: главы 12-39.
- Захват выполнен в одном авторизованном headless Chromium session.
- Между запросами глав выдерживались паузы `10-18` секунд.
- Полные HTML/TXT исходники сохранены вне Nextcloud в runtime.
- В wiki обновлены только манифесты, coverage map, пути, размеры и SHA256.
- Синтезированные wiki-страницы по главам 12-39 пока не создавались; статус в `coverage-map.md`: `raw-only`.

## [2026-04-26] raw-capture | metod8dev developers branch

- Сохранена ветка `Разработчикам` из `Методическая поддержка для разработчиков и администраторов 1С:Предприятия 8`.
- Захват выполнен в одном авторизованном headless Chromium session через resumable capture script.
- Сохранено `601` уникальное методическое/Q&A-документов, `0` failures.
- Полные HTML/TXT/JSON исходники сохранены вне Nextcloud в runtime.
- Runtime manifest: `/Users/olegrepnikov/Library/Application Support/WorkAssistant4/runtime/wiki/1c-language/raw/its-1c-metod8dev/developers/manifest.json`.
- В wiki обновлены только summary, manifest, coverage map, log и память.
- Статус источника: `raw-only`; следующий шаг — кластеризация документов по практическим темам и синтез answer-ready страниц.

## [2026-04-26] workflow | Telegram topic and answer-ready on demand

- Создана отдельная Telegram forum topic `wiki по 1С`, topic id `352`.
- Topic привязан к thread slug `wiki-1c-language`.
- Для темы создан topic-level `memory/threads/wiki-1c-language/AGENTS.md`.
- В `Wiki/1C-Language/AGENTS.md` и `quality.md` закреплен on-demand workflow:
  - не переводить весь raw-корпус в `answer-ready` заранее;
  - при реальном вопросе сначала искать существующую wiki-страницу;
  - если страницы недостаточно, искать raw-источники, создать/обновить `answer-ready` страницу и затем отвечать пользователю по ней.
- Дальнейшие вопросы по 1С должны маршрутизироваться в Telegram topic `wiki по 1С`.

## [2026-04-26] answer-ready | Исключения

- Страница `pages/syntax/exceptions.md` повышена со статуса `overview` до `answer-ready`.
- Добавлены практические случаи использования `Попытка ... Исключение` и `ВызватьИсключение`.
- Добавлены ограничения: неперехватываемые ошибки, асинхронность через `Ждать`, ошибка базы данных внутри транзакции.
- Обновлены `sources/coverage-map.md` и `sources/control-questions.md`.

## [2026-04-26] tooling | Local Codex service

- Добавлен локальный сервис доступа других Codex-тредов к `Wiki/1C-Language`.
- CLI: `tools/wiki_1c_query.py`.
- MCP-wrapper: `tools/wiki_1c_mcp.py`.
- Документация: `Docs/wiki-1c-service.md`.
- Сервис строит SQLite FTS index только по Markdown-слою wiki; полный raw-текст не копируется обратно в проект.
- По raw-слою сервис выполняет read-only поиск в runtime и возвращает только короткие snippets.
- Очередь curation-заявок: `data/wiki_1c_service/curation_queue/`.
- MCP-сервер `wiki-1c-language` зарегистрирован в пользовательском Codex-конфиге.
- Общий `AGENTS.md` уведомляет остальные Codex-треды: по вопросам 1С использовать сервис, а при `needs_curation=true` создавать заявку владельцу `wiki-1c-language`.
