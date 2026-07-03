# Architecture Adjustments

The external plan is accepted with these implementation boundaries:

1. Version 5 starts with the deterministic skill meta-model, not with business
   data skills. A broad seed catalog can hide architecture defects too early.
2. Skills are reusable contracts. 1C object names, field names, enum values, and
   register choices belong to `SkillBinding` or discovery evidence, not to
   business skill code.
3. LLM may propose intent, decomposition, candidate plans, bindings, repairs,
   and skill evolution. Deterministic code decides schema validity, type
   compatibility, plan validity, status policy, query safety, and whether a gap
   should extend an existing skill or create a new one.
4. The first executable core must prove this behavior:
   `resolve context -> get warehouses with semantic filters -> get stock
   balances -> render answer`, without creating narrow skills such as
   `get_wholesale_warehouses`.
5. Successful runs will later become regression cases, but the first increment
   writes enough trace data to support that pipeline.

6. Goal decomposition must use concrete business artifact types. `EntityRefList`,
   `TypedTable`, `EntityRef`, and `Answer` are technical base types for planning
   and rendering, not valid data goals. If the model cannot name a concrete
   artifact such as `WarehouseRefList`, `DocumentListTable`, or
   `StockBalanceTable`, planning must stop with a gap instead of selecting a
   nearby existing skill.
7. A data skill must not accept arbitrary semantic filters through `"*"`.
   Constraints are valid only when declared in the skill contract or when they
   target an explicit skill input. This prevents applying document filters to
   warehouse skills, stock filters to document skills, and similar cross-domain
   plan corruption.
8. Presentation skills may consume abstract input types, but the composer must
   bind those inputs to concrete goal artifacts before searching for producers.
   If no producer exists for the concrete artifact, the result is a learning gap,
   not a fallback to another table/list skill.
