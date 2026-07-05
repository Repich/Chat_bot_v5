# Metadata Explorer

Metadata Explorer helps a 1C expert inspect the current configuration before
creating or approving a skill.

## What To Check

For each object, inspect:

- full metadata name;
- object kind;
- synonym;
- confirmed fields;
- field hints;
- evidence source;
- onboarding query patterns and register usage when available.

## Trust Rules

Workbench separates confirmed fields from hints:

- MCP metadata and parsed XML metadata are verified sources.
- Query patterns, source-code matches, and onboarding candidates are hints.
- Hints cannot be used as final query facts until confirmed.

When a generated query fails metadata review, use Metadata Explorer to find the
actual object and field names, then update the draft rather than hard-coding a
Python workaround.

## API

```text
GET /api/admin/metadata/search?term=...
GET /api/admin/metadata/object?full_name=...
```

These endpoints are admin-protected because metadata can reveal business
structure.
