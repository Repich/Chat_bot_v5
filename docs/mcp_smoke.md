# MCP Smoke Diagnostic

This diagnostic checks whether WIICON5 can discover a `SkillBinding` from MCP
metadata and build a safe query draft for a skill.

It does not use LLM and does not answer user questions.

macOS/Linux:

```bash
python3 scripts/mcp_smoke.py --mcp-url http://127.0.0.1:6003 --skill-id get_warehouses --config local
```

Windows:

```bat
scripts\mcp_smoke.cmd --mcp-url http://127.0.0.1:6003 --skill-id get_warehouses --config local
```

For stock balance binding:

```bash
python3 scripts/mcp_smoke.py --skill-id get_stock_balances --config local
```

For generic document list discovery:

```bash
python3 scripts/mcp_smoke.py \
  --skill-id get_documents_by_type_and_period \
  --document-type "Заказ клиента" \
  --year 2024 \
  --config local
```

The command prints JSON with:

- `binding`: discovered or cached binding;
- `query_draft`: generated read-only 1C query draft.
