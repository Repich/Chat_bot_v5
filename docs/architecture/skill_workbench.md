# Skill Workbench Architecture

`5.0.0-alpha.79` replaces the previous human lifecycle with a simpler catalog
model.

## Design Decision

The old Workbench tried to model every generated skill as a draft/candidate that
had to pass preview, smoke, approval, regression replay, promotion, and stable
promotion. In practice this created a large UI surface and many defects.

The new rule is:

```text
If the agent can generalize a successful query into a learned skill, the skill is
accepted immediately.
```

Human review is corrective, not gating.

## Runtime Flow

1. Query synthesis answers a user question.
2. `LearnedSkillStore` checks whether the successful query can become a reusable
   learned skill.
3. If yes, the skill is written to `skills/learned/active/<skill_id>.json`.
4. The skill is added to the in-memory `SkillRegistry`.
5. The skill appears in `/api/admin/skills/catalog`.
6. The web Workbench lets a human inspect, edit, or delete it.

Raw synthesis candidates may still be recorded as diagnostic compatibility data
when no reusable learned skill is created, but they are not the primary
user-facing workflow.

## Editable Scope

Editable in UI:

- `learned_query` skills;
- bot-specific/user-created skills;
- files under a `learned` folder.

Protected in UI:

- seed skills under `skills/atomic`;
- bindings and non-skill JSON files;
- system files outside the skill catalog.

## API

The catalog endpoint exposes `user_editable`.

```text
GET    /api/admin/skills/catalog
GET    /api/admin/skills/catalog/<skill_id>
PATCH  /api/admin/skills/catalog/<skill_id>
DELETE /api/admin/skills/catalog/<skill_id>
```

`PATCH` accepts a full `skill` object or a narrower payload with
`description`, `implementation`, `query`, and `params`. The backend preserves
`skill_id`; learned skills remain active after update.

`DELETE` removes only editable learned/user skills. Protected seed skills return
403.

## Audit

Edits and deletes append audit events:

- `workbench.skill.updated`;
- `workbench.skill.deleted`.

The audit records before/after skill JSON and source path.

## Compatibility

Older draft/candidate/lifecycle services can remain in the backend for existing
tests, migration, and diagnostics. They are not exposed as the main web
Workbench path and should not be used as the product model for new work.
