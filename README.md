# WIICON ChatBot 5

WIICON ChatBot 5 - экспериментальный самообучающийся агент для ответов на
бизнес-вопросы по данным 1С через MCP-сервер.

Текущая версия: `5.0.0-alpha.73`.

Проект не является набором жестко зашитых обработчиков под отдельные вопросы.
Целевая модель: агент получает вопрос пользователя, учитывает контекст диалога,
проверяет существующие атомарные навыки, при необходимости изучает метаданные
текущей конфигурации 1С, строит безопасный read-only запрос и сохраняет
полезные успешные решения как переиспользуемые навыки.

## Документация

- [Обзор проекта](docs/project_overview.md): что это за проект, зачем он нужен,
  цели, нецели и текущий статус.
- [Архитектура](docs/architecture.md): основные компоненты, пайплайн обработки
  запроса, навыки, синтез запросов, MCP и трассировка.
- [Возможности](docs/capabilities.md): что агент уже умеет, что реализовано
  частично и какие ограничения есть сейчас.
- [Эксплуатация](docs/operations.md): запуск, настройки LLM/MCP, тесты, логи,
  трассы и релизный процесс.
- [Быстрый старт](docs/quickstart.md): короткие команды для локального запуска.
- [MCP smoke diagnostic](docs/mcp_smoke.md): проверка metadata discovery и
  binding без обращения к LLM.
- [Architecture adjustments](docs/architecture_adjustments.md): принятые
  технические границы разработки версии 5.
- [Skill Workbench architecture](docs/architecture/skill_workbench.md):
  human-in-the-loop lifecycle для просмотра, проверки и публикации навыков.
- [Skill Workbench overview](docs/workbench/overview.md): пользовательское
  описание Workbench и основного lifecycle.
- [Workbench user guide](docs/workbench/user_guide.md): как консультанту
  просматривать кандидатов, черновики, smoke и promotion.
- [Workbench data storage policy](docs/workbench/data_storage_policy.md):
  что можно хранить в Git, а что остается локальным evidence workspace.

История изменений:

- Backend: [docs/backend/history.txt](docs/backend/history.txt)
- Frontend: [docs/frontend/history.txt](docs/frontend/history.txt)

## Быстрый Старт

Запустить тесты:

```bash
python3 scripts/run_tests.py
```

Запустить локальный HTTP-сервис:

```bash
python3 scripts/run_server.py --host 127.0.0.1 --port 7785
```

Задать один вопрос из CLI:

```bash
python3 scripts/ask.py "Покажи склады"
```

Открыть web-клиент:

```text
http://127.0.0.1:7785/
```

Локальный MCP-прокси 1С по умолчанию ожидается на:

```text
http://127.0.0.1:6003
```

## Аварийная Диагностика Синтеза Запросов

Если агент не смог построить корректный запрос к данным, он сохраняет полный
диагностический пакет в trace:

```text
runs/<run_id>/diagnostics/query_synthesis_failure.json
```

Опционально можно включить аварийный solver, который получает этот контекст и
пытается вернуть новый безопасный read-only запрос 1С. Solver не меняет код
бота. Если задача требует доработки кода или MCP, агент возвращает пользователю
путь к диагностике для разработчика.

Через OpenAI-compatible API:

```bash
export WIICON5_FAILURE_SOLVER_ENABLED=true
export WIICON5_FAILURE_SOLVER_PROVIDER=openai_compatible
export WIICON5_FAILURE_SOLVER_API_BASE=https://api.openai.com/v1
export WIICON5_FAILURE_SOLVER_API_KEY=...
export WIICON5_FAILURE_SOLVER_MODEL=gpt-5.4
```

Через локальный Codex CLI adapter:

```bash
export WIICON5_FAILURE_SOLVER_ENABLED=true
export WIICON5_FAILURE_SOLVER_PROVIDER=codex_cli
export WIICON5_FAILURE_SOLVER_CODEX_COMMAND="python3 scripts/codex_failure_solver.py"
```
