# Skill Workbench Overview

Skill Workbench is the human control layer for WIICON ChatBot 5 skills. The
current model is intentionally simple:

```text
agent learns a reusable skill -> skill is active immediately
human reviews it -> human edits or deletes it when needed
```

There is no user-facing status workflow. The interface does not ask a consultant
to move a skill through candidate, approval, verified, and stable states.

## What The Workbench Shows

- catalog of loaded skills;
- readable skill purpose and applicability;
- inputs, outputs, capabilities, tags, implementation strategy;
- editable query/implementation for learned or bot-specific skills;
- raw JSON for diagnostics.

Seed skills from `skills/atomic` are read-only in the web UI. Learned skills and
bot-specific user skills are editable and deletable.

## Main Flow

```text
successful query synthesis
-> generalized learned skill
-> skills/learned/active/<skill_id>.json
-> runtime registry
-> Workbench catalog
-> edit or delete by human
```

If a learned skill is wrong, deleting it is the intended rejection path. The next
similar user question gives the agent a chance to build a better version using
current metadata, MCP results, and the latest prompts.

## What Remains Internal

Older draft/candidate endpoints can remain for compatibility, tests, and
diagnostics, but they are not the primary UI path. The Workbench screen is built
around the skill catalog, not around lifecycle queues.
