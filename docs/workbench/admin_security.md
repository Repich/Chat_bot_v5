# Workbench Admin Security

Workbench endpoints under `/api/admin/*` can inspect metadata, start onboarding,
and edit or delete learned/user-created skills. They are admin functionality.

## Settings

Configure security through environment variables or `.env.wiicon5`:

```text
WIICON5_ADMIN_ENABLED=true
WIICON5_ADMIN_TOKEN=
WIICON5_ADMIN_BIND_LOCAL_ONLY=true
WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS=/path/to/config/root
WIICON5_WORKBENCH_ALLOW_RAW_QUERY_EDIT=false
```

Rules:

- `WIICON5_ADMIN_ENABLED=false` disables all `/api/admin/*` endpoints.
- `WIICON5_ADMIN_BIND_LOCAL_ONLY=true` allows admin calls only from loopback
  clients such as `127.0.0.1` or `::1`.
- If `WIICON5_ADMIN_TOKEN` is set, admin calls must pass either
  `Authorization: Bearer <token>` or `X-WIICON5-Admin-Token: <token>`.
- `WIICON5_ADMIN_ALLOWED_CONFIG_ROOTS` limits onboarding config dump paths. Use
  the platform path separator for multiple roots.
- `WIICON5_WORKBENCH_ALLOW_RAW_QUERY_EDIT=false` keeps legacy manual raw-query
  draft editing disabled. Leave it off unless an architect is intentionally
  using old diagnostic endpoints.

The regular `/chat`, `/health`, history, and version endpoints do not require the
admin token.

Denied admin requests write compact `workbench.admin.denied` audit events without
recording secret tokens.
