# Граница передачи данных в LLM

## Инвариант

Все runtime-данные агента классифицируются как `confidential` по умолчанию:

- сообщения и история пользователя;
- строки, параметры и ответы MCP/1С;
- метаданные и выгрузка конфигурации;
- документация экземпляра и BWiki;
- навыки, трассировки, диагностика и результаты проверок.

Такие данные разрешено передавать только LLM endpoint, который одновременно:

1. явно помечен `WIICON5_LLM_TRUST_ZONE=internal`;
2. имеет hostname из `WIICON5_INTERNAL_LLM_ALLOWED_HOSTS`.

При несовпадении transport отклоняет вызов до открытия HTTP-соединения. Ошибка
внутренней модели не вызывает fallback во внешнюю модель.

## Почему нет распознавания персональных данных

Regex и NER не дают гарантии: ФИО, адрес или иной идентификатор могут находиться
в произвольном поле, комментарии, документации либо представлении ссылки 1С.
Поэтому граница не пытается угадать, содержит ли конкретный payload персональные
данные. Весь рабочий контекст считается конфиденциальным.

## Настройка внутренней GLM

```env
WIICON5_LLM_API_BASE=https://glm.internal.example/v1
WIICON5_LLM_API_KEY=...
WIICON5_LLM_MODEL=glm-5.2
WIICON5_LLM_TRUST_ZONE=internal
WIICON5_INTERNAL_LLM_ALLOWED_HOSTS=glm.internal.example
```

В allowlist указывается только точный hostname без схемы и пути. Несколько имен
разделяются запятой или точкой с запятой.

Если `trust_zone=external`, пользовательский runtime продолжит запускаться, но
любой LLM-вызов с рабочими данными будет заблокирован. Это позволяет открыть UI,
увидеть состояние защиты и исправить конфигурацию без утечки данных.

## Failure solver

`codex_cli` запрещен для runtime-диагностики, поскольку она содержит сообщения,
данные 1С и документацию. OpenAI-compatible failure solver разрешен только как
явно настроенный внутренний endpoint с отдельным trust zone и allowlist:

```env
WIICON5_FAILURE_SOLVER_ENABLED=true
WIICON5_FAILURE_SOLVER_PROVIDER=openai_compatible
WIICON5_FAILURE_SOLVER_API_BASE=https://glm.internal.example/v1
WIICON5_FAILURE_SOLVER_API_KEY=...
WIICON5_FAILURE_SOLVER_MODEL=glm-5.2
WIICON5_FAILURE_SOLVER_TRUST_ZONE=internal
WIICON5_FAILURE_SOLVER_INTERNAL_ALLOWED_HOSTS=glm.internal.example
```

## Аудит

Для каждого разрешенного или заблокированного вызова журнал содержит:

- решение `allow`/`block`;
- trust zone и классификацию;
- hostname и модель;
- SHA-256 payload.

Содержимое prompt, payload и значения персональных данных в audit-сообщение не
записываются. Текущее состояние границы отображается в UI и `/health`.

## Граница гарантии

Приложение гарантирует отсутствие сетевого LLM-вызова с `confidential` payload
в endpoint, помеченный как `external`. Администратор инфраструктуры отвечает за
то, что hostname, внесенный в internal allowlist, действительно принадлежит
утвержденному внутреннему контуру и защищен на сетевом и TLS-уровне.
