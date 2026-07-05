# Skill Workbench Architecture

## Purpose

Skill Workbench is the human-in-the-loop layer for WIICON ChatBot 5 skill
development. It lets a 1C expert, consultant, or advanced business user inspect,
draft, validate, test, and approve skills without editing Python code or raw
`SkillContract` JSON.

The Workbench exists because the agent can synthesize useful queries, but the
business meaning of a skill still needs human review:

- what business question the skill answers;
- which 1C objects and fields are involved;
- which fields represent product, warehouse, counterparty, amount, date, status,
  and other business roles;
- how the result is calculated;
- how to prove that the answer is correct for the current configuration.

The user confirms business semantics and data structure. The system generates
formal, validated artifacts that runtime can use.

## Non-Goals

The Workbench is not a free-form JSON editor and not a raw query console.

By default it must not allow:

- direct editing of runtime skill JSON;
- direct publication of a skill without validation;
- promotion to `verified` without a successful smoke test and human approval;
- treating onboarding hints as confirmed metadata fields;
- automatic activation of candidate skills in production planning;
- arbitrary MCP query execution from admin screens;
- raw 1C query editing outside a separately enabled advanced mode.

## Primary User

The primary user is not necessarily a programmer. The Workbench must be usable by
a person who knows the 1C configuration, business terminology, documents,
registers, and reports well enough to reason about the data model.

The interface should present both views:

- business view: product, warehouse, balance, retail store, largest value;
- technical view: `РегистрНакопления.ТоварыНаСкладах.Остатки()`,
  `Номенклатура`, `Склад`, `ВНаличииОстаток`.

## Core Concepts

### Skill

A formal runtime contract that the planner and executor can use. A skill defines
capabilities, typed inputs, typed outputs, supported filters, implementation
strategy, and metadata dependency contracts.

### Human Skill Draft

A human-readable draft that is safe to edit in Workbench. It is not a runtime
skill and is not plannable.

A draft describes:

- title and business description;
- example user questions;
- business entities and roles;
- 1C data sources;
- field mappings;
- filter recipes;
- calculation recipe;
- presentation recipe;
- notes, source, trace path, status, and audit metadata.

### Binding

A mapping between business roles and concrete metadata in one configuration:

- `product -> Остатки.Номенклатура`;
- `warehouse -> Остатки.Склад`;
- `stock_balance -> Остатки.ВНаличииОстаток`;
- `warehouse_type -> Справочник.Склады.ТипСклада`.

Bindings must be configuration-specific and backed by metadata evidence.

### Calculation Recipe

A structured, non-code description of a calculation:

- source;
- filters;
- group by;
- aggregate measures;
- sort;
- limit;
- presentation fields.

Deterministic builders should turn supported recipes into read-only 1C queries.
LLM assistance may propose drafts, but publishing must rely on deterministic
validation gates.

### Evidence

Evidence explains why a skill is trusted:

- metadata objects confirmed by MCP or XML configuration dump;
- fields confirmed by MCP or XML metadata;
- query preview passed safety and query review;
- smoke test executed successfully;
- sample result reviewed by a human;
- regression case created;
- trace and audit events recorded.

Hints from source-code grep, onboarding candidates, query patterns, or LLM
reasoning are useful evidence, but they are not confirmed fields until verified
against MCP or XML metadata.

### Approval

Approval is a human action with actor, timestamp, comment, level, smoke test
evidence, and optional regression evidence. Approval records are append-only
audit facts and must not silently overwrite earlier approval history.

## Lifecycle

The Workbench lifecycle is intentionally slower than automatic query synthesis:

```text
onboarding / trace / manual input
-> HumanSkillDraft
-> validation
-> query preview
-> smoke test through MCP
-> human approval
-> candidate SkillContract
-> regression evidence
-> verified
-> stable
```

Allowed transitions:

```text
draft -> ready_for_validation
ready_for_validation -> validated
validated -> candidate
candidate -> verified
verified -> stable
candidate/verified/stable -> deprecated
any -> blocked
```

Forbidden transitions:

```text
draft -> verified
candidate -> stable
failed_smoke -> verified
blocked -> stable without explicit rollback/review
```

Candidate skills are not runtime-active by default. Runtime may use only
`verified` and `stable` skills unless a specific test/admin setting enables
candidate skills.

## Storage

Workbench data is bot-instance-specific:

```text
bot_instances/<bot_id>/workbench/drafts/<draft_id>.json
bot_instances/<bot_id>/workbench/audit/events.jsonl
bot_instances/<bot_id>/workbench/approvals/<skill_id>.json
bot_instances/<bot_id>/workbench/smoke/<draft_id>/<smoke_id>.json
bot_instances/<bot_id>/skills/candidates/<skill_id>.json
bot_instances/<bot_id>/skills/evidence/<skill_id>/...
bot_instances/<bot_id>/regression/<case_id>.json
```

Global seed skills remain read-only. Human-created drafts, candidates, evidence,
and approvals live under the bot instance workspace.

## Validation Gates

Before publishing a candidate, the system must verify:

- draft title is not empty;
- at least one example question exists;
- every required field mapping references a selected data source;
- all published fields are confirmed by MCP or XML metadata;
- calculation kind is supported;
- aggregate recipes have valid group-by and measure roles;
- generated query is read-only;
- query reviewer accepts the query;
- no unresolved template parameters remain;
- no empty list parameters will reach MCP;
- smoke test has succeeded.

Validation errors should be actionable for a 1C expert, not just Python
exceptions.

## Audit Trail

Every state-changing operation writes an append-only audit event:

- `workbench.draft.created`;
- `workbench.draft.updated`;
- `workbench.draft.deleted`;
- `workbench.validation.requested`;
- `workbench.validation.failed`;
- `workbench.validation.passed`;
- `workbench.query.previewed`;
- `workbench.smoke.started`;
- `workbench.smoke.completed`;
- `workbench.skill.published_candidate`;
- `workbench.skill.promoted`;
- `workbench.skill.deprecated`;
- `workbench.skill.blocked`;
- `workbench.raw_query.edited`.

Each event contains:

- `event_id`;
- `event_type`;
- `bot_id`;
- `actor`;
- timestamp;
- object ids;
- before/after hashes where applicable;
- compact payload.

Large result sets, secrets, API keys, and full environment payloads must not be
written to audit. Smoke samples must be capped and truncated.

## Relationship With Onboarding

Onboarding discovers metadata objects, field hints, register usage, query
patterns, and candidate bindings. It does not create verified runtime skills.

Workbench can turn onboarding candidates into drafts:

```text
onboarding candidate -> HumanSkillDraft -> validation -> smoke -> approval
```

This keeps automatic discovery useful while preserving human accountability.

## Relationship With Query Synthesis

Successful query synthesis can produce Workbench candidates when the generated
query was useful and sufficiently answered a business question. It must not
silently publish a verified skill.

Trace import may prefill:

- title;
- description;
- example question;
- data sources;
- field mappings inferred from the query;
- calculation recipe;
- presentation recipe;
- source trace path.

The created draft still needs human review.

## Relationship With Runtime

Runtime uses formal skills, not drafts. Workbench writes candidate skills into a
bot-specific skill workspace. The skill registry must preserve lifecycle status
and avoid plannable use of `candidate`, `deprecated`, and `blocked` skills unless
explicitly configured for test scenarios.

Runtime traces and Workbench audit serve different purposes:

- runtime traces explain one user request;
- Workbench audit explains who changed skill behavior and why.

## Security

Workbench endpoints are admin functionality. They can inspect metadata, run MCP
smoke queries, publish skills, and change agent behavior.

Minimum security rules:

- `/api/admin/*` endpoints must support admin enable/disable settings;
- admin token support is required before exposing state-changing endpoints
  beyond local development;
- onboarding paths must be restricted by allowlist;
- publish/promote/block actions require an actor;
- raw query editing is disabled unless explicitly enabled;
- smoke limits default to 10 rows and must not exceed a fixed cap.

## MVP Scope

The first useful MVP is:

1. architecture document;
2. HumanSkillDraft models, store, and audit;
3. read-only skill catalog;
4. metadata explorer;
5. draft import from trace;
6. draft CRUD;
7. deterministic query preview for `top_n_by_metric`;
8. MCP smoke test;
9. publish candidate;
10. minimal web UI.

The first implementation phases must not start with UI or raw query editing.

