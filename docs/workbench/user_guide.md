# Workbench User Guide

Use Workbench when the agent found a useful query, when onboarding suggests a
candidate, or when an expert wants to define a reusable business skill.

## 1. Inspect Existing Skills

Open `Settings -> Skill Workbench -> Навыки`. The Workbench panel shows a
human-readable summary first and keeps the raw JSON below it for diagnostics.

To open one skill, paste its `skill_id` into `Skill ID` and click
`Открыть skill`.

Check:

- status: `candidate`, `verified`, `stable`, `deprecated`, or `blocked`;
- example capabilities and supported filters;
- inputs and outputs;
- source path and whether the skill is bot-specific;
- runtime activity flag.

`candidate`, `deprecated`, and `blocked` skills are visible for review but are
not used by the agent by default.

## 2. Review Candidates

Workbench has candidate queues from:

- onboarding files;
- successful query synthesis;
- imported skill packs;
- traces converted into drafts.

Use `Onboarding candidates` and `Agent candidates` to load the queues. For each
candidate, either create a draft, reject it, or ignore similar future
suggestions. Candidate summaries are for review; the full evidence remains in
the raw JSON block.

## 3. Edit A Draft

A draft should describe business meaning, not code:

- title and description;
- example questions;
- 1C data sources;
- field mappings and business roles;
- filters;
- calculation recipe;
- presentation columns and notes.

Hints from onboarding are useful, but final query fields must be confirmed by
MCP or verified XML metadata.

For the first supported manual scenario, use the guided `top_n_by_metric` form:

- source object: the 1C register, document table, or virtual table name;
- grouping role and field;
- metric role and field;
- optional filter role and field;
- aggregation and limit;
- field confirmation flag after checking metadata.

`Draft JSON` is an advanced override. Leave it empty for normal consultant use.

## 4. Validate And Smoke

Before publication:

1. Generate preview query.
2. Review warnings and validation issues.
3. Run MCP smoke test.
4. Inspect sample rows.
5. Approve only if the business meaning and result are correct.

Smoke test samples are intentionally limited; they are evidence, not a full data
export.

## 5. Publish And Promote

Publishing creates a `candidate` skill. To make it runtime-active:

1. Create or choose regression cases.
2. Run regression replay from the Workbench panel.
3. Paste the skill id into `Skill ID`, add the regression case ids and a reason,
   then promote candidate to `verified`.
4. Later promote verified to `stable` after successful runs or explicit admin
   approval.

Use `block` for unsafe or incorrect skills and `deprecated` for replaced skills.
