# Index — Wiki Язык 1С

## Overview

- [README](README.md) — назначение и структура wiki.
- [Schema](AGENTS.md) — правила сопровождения wiki агентом.
- [Sources](sources/manifest.md) — реестр источников.
- [Developer Guide Structure](sources/developer-guide-structure.md) — структура `Руководства разработчика` 8.3.27.
- [Quality Policy](quality.md) — критерии готовности wiki-страниц.
- [Coverage Map](sources/coverage-map.md) — карта покрытия источников wiki-страницами.
- [Control Questions](sources/control-questions.md) — тестовые вопросы для проверки качества.
- [Log](log.md) — журнал изменений.

## Concepts

- `pages/concepts/` — ключевые понятия языка и платформы.
- [Конфигурация](pages/concepts/configuration.md)
- [Объект конфигурации](pages/concepts/configuration-object.md)
- [Объекты конфигурации: обзор](pages/concepts/configuration-objects-overview.md)
- [Справочники](pages/concepts/catalogs.md)
- [Документы](pages/concepts/documents.md)
- [Отчеты и обработки](pages/concepts/reports-and-processings.md)
- [Регистры](pages/concepts/registers.md)
- [Планы обмена](pages/concepts/exchange-plans.md)
- [Бизнес-процессы и задачи](pages/concepts/business-processes-and-tasks.md)

## Syntax

- `pages/syntax/` — синтаксис встроенного языка.
- [Встроенный язык](pages/syntax/built-in-language.md)
- [Программные модули](pages/syntax/program-modules.md)
- [Контексты выполнения модулей](pages/syntax/module-contexts.md)
- [Виды программных модулей](pages/syntax/module-types.md)
- [Формат программного модуля](pages/syntax/module-format.md)
- [Типы данных и значения](pages/syntax/data-types-and-values.md)
- [Выражения и операции](pages/syntax/expressions-and-operations.md)
- [Операторы и управляющие конструкции](pages/syntax/operators-and-control-flow.md)
- [Циклы](pages/syntax/cycles.md)
- [Процедуры и функции](pages/syntax/procedures-and-functions.md)
- [Исключения](pages/syntax/exceptions.md)
- [Основные приемы работы во встроенном языке](pages/syntax/common-work-techniques.md)
- [Синхронные и асинхронные методы](pages/syntax/sync-async-methods.md)
- [Препроцессор и директивы компиляции](pages/syntax/preprocessor-and-compilation-directives.md)

## Runtime

- `pages/runtime/` — выполнение кода, контексты, ошибки, обработчики.
- [Разработка и исполнение](pages/runtime/development-and-execution.md)
- [Работа с данными](pages/runtime/data-work.md)
- [Транзакции](pages/runtime/transactions.md)
- [Блокировки](pages/runtime/locks.md)
- [Управляемые блокировки](pages/runtime/managed-locks.md)
- [Индексы и динамические выборки](pages/runtime/indexes-and-dynamic-selections.md)

## Query Language

- `pages/query-language/` — язык запросов 1С.
- [Работа с запросами](pages/query-language/queries.md)
- [Источники данных запроса](pages/query-language/query-sources.md)
- [Структура языка запросов](pages/query-language/query-language-structure.md)
- [Соединения и вложенные запросы](pages/query-language/query-joins-and-nested-queries.md)
- [Временные таблицы](pages/query-language/temporary-tables.md)
- [Параметры и результат запроса](pages/query-language/query-parameters-and-results.md)

## Platform

- `pages/platform/` — механизмы платформы, влияющие на разработку.
- [Введение в Руководство разработчика](pages/platform/developer-guide-introduction.md)
- [Концепция системы 1С:Предприятие](pages/platform/system-concept.md)
- [Варианты работы платформы](pages/platform/runtime-variants.md)
- [Работа с конфигурацией](pages/platform/configuration-work.md)
- [Дерево объектов конфигурации](pages/platform/metadata-tree.md)
- [Конфигурация базы данных и реструктуризация](pages/platform/configuration-database-and-restructuring.md)
- [Интерфейс приложения](pages/platform/application-interface.md)
- [Структура интерфейса приложения](pages/platform/application-interface-structure.md)
- [Интерфейс Такси](pages/platform/taxi-interface.md)
- [Навигация, поиск, избранное и история](pages/platform/application-navigation-search.md)
- [Командный интерфейс](pages/platform/command-interface.md)
- [Подсистемы](pages/platform/subsystems.md)
- [Общие модули](pages/platform/common-modules.md)
- [Роли и права](pages/platform/roles-and-rights.md)
- [Командная модель](pages/platform/command-model.md)
- [Навигационные ссылки](pages/platform/navigation-links.md)
- [Формы](pages/platform/forms.md)
- [Данные формы](pages/platform/form-data.md)
- [Динамический список](pages/platform/dynamic-list.md)
- [Элементы и события формы](pages/platform/form-elements-events.md)
- [Система компоновки данных](pages/platform/data-composition-system.md)
- [Схема компоновки данных](pages/platform/dcs-schema.md)
- [Наборы данных СКД](pages/platform/dcs-data-sets.md)
- [Настройки и вывод СКД](pages/platform/dcs-settings-and-output.md)
- [Бухгалтерский учет](pages/platform/accounting.md)
- [Модель бухгалтерского учета](pages/platform/accounting-model.md)
- [Планы счетов и регистры бухгалтерии](pages/platform/chart-of-accounts-and-accounting-registers.md)

## Initial Source Map

- ITS 1C documentation v8.3.27: `https://its.1c.ru/db/v8327doc`.
- Key initial section: `Руководство разработчика`.
- First candidate for deep split: `Глава 4. Встроенный язык`.
