# Quickstart

Run tests:

```bash
python3 scripts/run_tests.py
```

Configure LLM/MCP with environment variables or a local `.env.wiicon5` file:

```env
WIICON5_LLM_API_BASE=https://api.deepseek.com
WIICON5_LLM_API_KEY=...
WIICON5_LLM_MODEL=deepseek-chat
WIICON5_MCP_URL=http://127.0.0.1:6003
```

`DEEPSEEK_API_BASE` / `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` and
`WIICON4_LLM_*` are accepted as fallbacks for local migration.

Check MCP metadata discovery without LLM:

```bash
python3 scripts/mcp_smoke.py \
  --mcp-url http://127.0.0.1:6003 \
  --skill-id get_warehouses \
  --config local \
  --timeout 15 \
  --max-search-terms 3 \
  --metadata-limit 20
```

Check stock balance binding:

```bash
python3 scripts/mcp_smoke.py \
  --mcp-url http://127.0.0.1:6003 \
  --skill-id get_stock_balances \
  --config local \
  --timeout 20 \
  --max-search-terms 4 \
  --metadata-limit 20
```

Run one CLI question:

```bash
python3 scripts/ask.py "Покажи склады"
```

For stock balances, seed dialog context with a real objectRef JSON returned by MCP:

```bash
python3 scripts/ask.py \
  --product-ref '{"_objectRef":true,"УникальныйИдентификатор":"...","ТипОбъекта":"СправочникСсылка.Номенклатура","Представление":"..."}' \
  "Покажи остатки товара"
```

Run HTTP server:

```bash
python3 scripts/run_server.py --host 127.0.0.1 --port 7785
```

POST a chat message:

```bash
curl -s http://127.0.0.1:7785/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"test","message":"Покажи склады"}'
```

Current live limitation:

- local MCP metadata discovery must return from `/api/get_metadata`;
- product resolution by article/name is not implemented yet; seed `ProductRef` must come
  from dialog context or an external lookup;
- if MCP metadata times out, `mcp_smoke.py` prints metadata diagnostics and no binding is created.
