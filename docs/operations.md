# Эксплуатация

## Настройка

Сервис читает настройки из переменных окружения или локального файла
`.env.wiicon5`.

Основные переменные:

```env
WIICON5_LLM_API_BASE=https://api.deepseek.com
WIICON5_LLM_API_KEY=...
WIICON5_LLM_MODEL=deepseek-chat
WIICON5_MCP_URL=http://127.0.0.1:6003
WIICON5_BOT_ID=local
WIICON5_CONFIG_FINGERPRINT=local
```

Для локальной миграции также принимаются старые имена:

- `DEEPSEEK_API_BASE`;
- `DEEPSEEK_API_KEY`;
- `DEEPSEEK_MODEL`;
- `WIICON4_LLM_*`.

Bot instance по умолчанию читается из:

```text
bot_instances/local/bot.yaml
```

Полезные переменные bot workspace:

- `WIICON5_BOT_ID`: id экземпляра, например `local` или `client_a`;
- `WIICON5_BOT_ROOT`: явный путь к каталогу bot instance;
- `WIICON5_BOT_CONFIG`: явный путь к `bot.yaml`;
- `WIICON5_CONFIG_FINGERPRINT`: ручной fingerprint или `auto`.

Если указать `WIICON5_CONFIG_FINGERPRINT=auto`, сервис при старте построит
начальный fingerprint по доступным metadata objects из MCP. Отдельно от этого
сервис умеет использовать предварительно построенный onboarding index из
`bot_instances/<id>/onboarding/metadata_index.sqlite`.

Опциональный аварийный solver для неудачного синтеза запросов включается
отдельно от основной модели:

```env
WIICON5_FAILURE_SOLVER_ENABLED=true
WIICON5_FAILURE_SOLVER_PROVIDER=openai_compatible
WIICON5_FAILURE_SOLVER_API_BASE=https://api.openai.com/v1
WIICON5_FAILURE_SOLVER_API_KEY=...
WIICON5_FAILURE_SOLVER_MODEL=gpt-5.4
WIICON5_FAILURE_SOLVER_TIMEOUT_SECONDS=120
```

Если ChatGPT API недоступен с текущего компьютера, можно использовать локальный
Codex CLI adapter:

```env
WIICON5_FAILURE_SOLVER_ENABLED=true
WIICON5_FAILURE_SOLVER_PROVIDER=codex_cli
WIICON5_FAILURE_SOLVER_CODEX_COMMAND=python3 scripts/codex_failure_solver.py
```

Solver получает diagnostic payload и может вернуть только новый read-only
запрос 1С или решение `needs_developer`/`cannot_solve`. Автоматически изменять
код бота этот слой не должен.

## Локальный Запуск

Запустить HTTP-сервис:

```bash
python3 scripts/run_server.py --host 127.0.0.1 --port 7785
```

Открыть web-клиент:

```text
http://127.0.0.1:7785/
```

Отправить raw HTTP-запрос:

```bash
curl -s http://127.0.0.1:7785/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"test","message":"Покажи склады"}'
```

Задать один вопрос через CLI:

```bash
python3 scripts/ask.py "Покажи склады"
```

## MCP Smoke Checks

Проверить metadata discovery и binding без LLM:

```bash
python3 scripts/mcp_smoke.py \
  --mcp-url http://127.0.0.1:6003 \
  --skill-id get_warehouses \
  --config local
```

Проверить binding остатков:

```bash
python3 scripts/mcp_smoke.py \
  --mcp-url http://127.0.0.1:6003 \
  --skill-id get_stock_balances \
  --config local
```

Windows wrappers находятся в `scripts/*.cmd`.

## Onboarding Выгрузки Конфигурации

Построить candidates из файловой выгрузки 1С:

```bash
python3 scripts/onboard_config.py \
  --config-dump ./config_dump \
  --bot-instance ./bot_instances/client_a \
  --mcp-url http://127.0.0.1:6003
```

Результаты появятся в:

```text
bot_instances/client_a/onboarding/
```

CLI пишет `training_status.json`, поэтому web-клиент увидит bot instance как
обученный после успешного запуска.

То же можно запустить из web-клиента: в левом блоке `Первоначальное обучение`
указать путь к файловой выгрузке и нажать `Запустить обучение`. Пока обучение
не выполнено, web-клиент показывает предупреждающую плашку.

Это candidates, а не утвержденные skills/bindings. Индекс метаданных
используется как fallback при поиске объектов; детали объекта и корректность
запроса по-прежнему проверяются через MCP и reviewer.

XML-выгрузка 1С считается verified evidence для структуры объекта. Поля,
найденные только regex по исходникам, записываются как hints и не должны
использоваться как финальные поля query без подтверждения.

Проверить candidate bindings через MCP:

```bash
python3 scripts/verify_onboarding_candidates.py \
  --bot-instance ./bot_instances/client_a \
  --mcp-url http://127.0.0.1:6003 \
  --timeout 5 \
  --max-objects 50
```

Результат пишется в:

```text
bot_instances/client_a/onboarding/verified_binding_candidates.json
```

Параметры `--max-objects` и `--max-candidates` полезны для диагностических
прогонов, если MCP отвечает медленно. Полный прогон можно выполнять без лимитов.

## Regression Cases

Создать case из trace:

```bash
python3 scripts/trace_to_case.py runs/agent_... \
  --cases-dir bot_instances/local/regression \
  --expected-ok
```

Проверить набор cases:

```bash
python3 scripts/run_regression.py --cases bot_instances/local/regression
```

Выполнить replay cases через агента и сохранить результат в workspace бота:

```bash
python3 scripts/run_regression.py \
  --cases bot_instances/local/regression \
  --replay
```

Для перевода candidate skill в verified нужен успешный replay по связанным
`case_id`; одного наличия regression case теперь недостаточно.

## Skill Packs

Экспортировать выбранные skills в переносимый pack:

```bash
python3 scripts/export_skill_pack.py \
  --skills get_stock_balances get_warehouses \
  --include-bindings \
  --out releases/skill_pack_stock.json
```

Импортировать pack в bot workspace как candidate skills:

```bash
python3 scripts/import_skill_pack.py \
  --file releases/skill_pack_stock.json \
  --include-bindings \
  --actor consultant
```

Импортированные skills не становятся доверенными автоматически. В текущей
упрощенной модели их нужно открыть в каталоге навыков, проверить контракт и
запрос, затем оставить, исправить или удалить. Старые lifecycle endpoint-ы могут
оставаться для совместимости и диагностики, но не являются основным workflow.

## Тесты

Запустить все тесты:

```bash
python3 scripts/run_tests.py
```

Прямой запуск через unittest:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## Логи И Trace

Самые полезные диагностические данные лежат в:

```text
runs/agent_*
```

При разборе неправильного ответа нужно смотреть последний подходящий run:

- `input/user_message.json`: точное сообщение пользователя;
- `input/conversation_packet.json`: контекст и артефакты, доступные агенту;
- `intent/intent_response.json`: результат intent/decomposition;
- `intent/goal_decomposition.json`: целевой typed artifact;
- `skill_plan/plan_graph.json`: выбранный skill plan, если был;
- `skill_invocations/execution_result.json`: результат runtime, если был;
- `query_synthesis/`: поиск метаданных, LLM query draft, reviews, MCP calls и
  проверки достаточности;
- `diagnostics/query_synthesis_failure.json`: полный пакет для разработчика,
  если query synthesis окончательно не смог ответить;
- `clarification/resolution.json`: детерминированное разрешение уточнения;
- `result/result.json`: финальный ответ агента и source.

Для инцидентов с LLM-провайдером нужны:

- request_id из ответа `/chat`;
- server logs вокруг этого request_id;
- соответствующая папка `runs/agent_*`;
- ответ LLM diagnostics, если endpoint доступен в текущем build;
- модель, API base, timeout, SSL verify setting и форма payload.

## Версионирование И Релизы

Каждое изменение репозитория должно обновлять версию и историю.

Файлы версии:

- `VERSION`;
- `pyproject.toml`;
- `src/wiicon5/__init__.py`;
- `README.md`;
- `docs/backend/history.txt` или `docs/frontend/history.txt`.

## Auto-Learned Skill Settings

Для экспериментального режима автосоздания навыков используются настройки:

```text
WIICON5_AUTO_LEARNED_SKILLS_ENABLED=true
WIICON5_AUTO_LEARNED_SKILLS_ACTIVATE=true
WIICON5_AUTO_LEARNED_SKILLS_SCOPE=bot
WIICON5_AUTO_LEARNED_SKILLS_FAILURE_THRESHOLD=3
```

`scope=bot` хранит навыки в `bot_instances/<bot_id>/skills/learned`, поэтому
разные базы и профили не загрязняют общий каталог. `scope=global` допустим
только для осознанного общего эксперимента. Сводка доступна через
`GET /api/admin/learning/report` и вкладку `Обучение`.

Релизные архивы складываются во внешний общий каталог:

```text
/Users/repnikov/Nextcloud/PycharmProjects/NewWiiconChatBot/releases
```

Для легкого пакета используется `git archive`, чтобы не включать runtime traces,
virtualenv, локальные кэши и временные файлы.
