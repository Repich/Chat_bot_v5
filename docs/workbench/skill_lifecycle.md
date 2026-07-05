# Skill Lifecycle

Workbench uses explicit skill statuses.

## Statuses

- `candidate`: created from a draft, import, or generated evidence; not active by
  default.
- `verified`: reviewed, smoke-tested, approved, and regression-replayed; active.
- `stable`: mature verified skill; active.
- `deprecated`: replaced or obsolete; inactive.
- `blocked`: unsafe or wrong; inactive.

## Allowed Transitions

```text
candidate -> verified
verified -> stable
candidate/verified/stable -> deprecated
any non-draft skill -> blocked
deprecated/blocked -> candidate/verified/stable by explicit rollback
```

Direct `candidate -> stable` is forbidden.

## Promotion Gates

`candidate -> verified` requires:

- published candidate skill;
- human approval evidence;
- at least one regression case id;
- successful replay result for every supplied case id.

`verified -> stable` requires:

- enough successful runs, or
- explicit admin approval with a reason.

Every transition updates the bot-specific skill file, moves it into the matching
status folder, appends lifecycle evidence, and writes an audit event.
