# WIICON ChatBot 5

Skill-first self-improving agent for unknown 1C configurations.

Current version: `5.0.0-alpha.4`.

Version 5 starts from a new architecture. Business questions are decomposed into
typed artifacts, then solved through a graph of atomic skills. Data skills bind
to the current 1C configuration through metadata discovery and MCP execution;
they must not hardcode object names, field names, enum values, or narrow
business handlers.

## Current Increment

This repository currently contains the first runnable local increment:

- skill, binding, plan, invocation, artifact, and gap contracts;
- skill registry and graph search primitives;
- composer for executable skill DAGs;
- deterministic gap detection for extend-vs-create decisions;
- conversation context, intent/decomposition contracts, and agent orchestration
  for `message -> goal -> skill plan -> execution -> answer`;
- typed-artifact skill plan runtime;
- MCP/query contracts and data skill runner with read-only validation before MCP;
- parameterized 1C query execution through MCP `params`, including objectRef reuse;
- binding store/resolver/discoverer contracts;
- semantic query builder that uses `SkillBinding` for 1C object and field names;
- metadata discovery from local MCP with role profiles and object/field compatibility checks;
- baseline general answers and out-of-scope handling before/around LLM decomposition;
- LLM goal decomposition with an available-skills catalog and deterministic goal completion;
- stdlib HTTP MCP adapter for `/api/execute_query` and `/api/get_metadata`;
- stdlib HTTP `/health` and `/chat` service;
- stdlib HTTP `/api/version`, `/api/conversation`, `/history/backend`, and
  `/history/frontend` endpoints for the local web client;
- web client with sticky message composer, version display, session history
  reload, and backend/frontend history viewers;
- audit trace writer;
- unit tests for the skill-first behavior.

Validated live against local MCP for warehouse listing and stock balances through
`РегистрНакопления.ТоварыНаСкладах.Остатки()`.

## Test

macOS/Linux:

```bash
python3 scripts/run_tests.py
```

Windows:

```bat
scripts\run_tests.cmd
```

## MCP Smoke

When the local 1C MCP proxy is available, run:

```bash
python3 scripts/mcp_smoke.py --mcp-url http://127.0.0.1:6003 --skill-id get_warehouses --config local
```

See [docs/mcp_smoke.md](docs/mcp_smoke.md).

For service startup and one-shot CLI usage, see [docs/quickstart.md](docs/quickstart.md).

Change history:

- Backend: [docs/backend/history.txt](docs/backend/history.txt)
- Frontend: [docs/frontend/history.txt](docs/frontend/history.txt)
