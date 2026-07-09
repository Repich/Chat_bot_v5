# Workbench Data Storage Policy

Skill Workbench writes two different classes of data.

## Repository Data

These files are safe to keep in the repository when they are sanitized and
reviewed:

- shared seed skills under `skills/atomic/`;
- shared non-secret documentation under `docs/`;
- portable skill packs intentionally exported into `releases/`;
- synthetic regression cases that do not contain client names, live document
  numbers, sample rows, or private configuration structure.

## Local Bot Workspace Data

The following paths are local evidence/workspace data by default and should not
be committed accidentally:

- `bot_instances/<bot_id>/workbench/drafts/`;
- `bot_instances/<bot_id>/workbench/approvals/`;
- `bot_instances/<bot_id>/workbench/audit/`;
- `bot_instances/<bot_id>/workbench/smoke/`;
- `bot_instances/<bot_id>/runs/`;
- `bot_instances/<bot_id>/skills/learned/active/`;
- legacy diagnostic folders such as `bot_instances/<bot_id>/skills/candidates/`;
- `bot_instances/<bot_id>/skills/evidence/`;
- `bot_instances/<bot_id>/regression/results/`.

These files can contain real business questions, metadata names, query text,
sample rows, approval comments, and trace paths. Treat them as diagnostic
evidence, not as product source.

## Sharing Rule

If a bot-specific skill must be shared, export it as a skill pack and review the
pack contents before committing or transferring it. Imported or learned skills
should be checked in the catalog after import; delete or edit them if they are
too specific for the target bot instance.

## Regression Cases

Regression cases may be committed only when they are synthetic or sanitized.
Replay results stay local because they capture runtime answers and traces.
