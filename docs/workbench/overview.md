# Skill Workbench Overview

Skill Workbench is the human review layer for WIICON ChatBot 5. It lets a 1C
expert or strong business user inspect, create, test, approve, and promote agent
skills without editing Python code.

The key rule is simple:

```text
The human confirms business meaning and data structure.
The system generates and verifies the formal skill.
```

Workbench works with bot-specific data under `bot_instances/<bot_id>/`:

- human-readable skill drafts;
- onboarding and query-synthesis candidates;
- query preview and smoke evidence;
- approval records;
- regression cases and replay results;
- candidate, verified, stable, deprecated, and blocked skills;
- append-only audit events.

## Main Flow

```text
onboarding/query synthesis/trace/manual draft
-> HumanSkillDraft
-> preview query
-> MCP smoke test
-> human approval
-> candidate skill
-> regression replay
-> verified skill
-> stable skill
```

Candidate skills are not runtime-active by default. The agent can use promoted
`verified` and `stable` skills.

## What Workbench Is Not

Workbench is not a raw JSON editor and not a shortcut around validation. Imported
skills, onboarding hints, and generated queries stay as candidates until the
normal review lifecycle has been completed.
