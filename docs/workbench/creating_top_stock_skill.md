# Tutorial: Top Stock Skill

This example creates a reusable skill for the question:

```text
Покажи какого товара больше всего в розничном магазине?
```

## 1. Find Data Sources

Open `Settings -> Skill Workbench`. Use `Поиск метаданных` to find the stock
balance register. In many trade configurations this will be an accumulation
register with product, warehouse, and quantity fields.

Example target source:

```text
РегистрНакопления.ТоварыНаСкладах.Остатки()
```

Use `Metadata full_name -> Открыть объект` for the exact object card. Then find
the warehouse catalog and the field that identifies a retail store.

## 2. Create Draft

In the guided draft form fill:

- title: `Товар с максимальным остатком в розничных магазинах`;
- example question: `Покажи какого товара больше всего в розничном магазине?`;
- source alias: `Остатки`;
- source object: stock balance register or virtual table;
- grouping role: `product`;
- grouping field: product field, for example `Номенклатура`;
- metric role: `stock_balance`;
- metric field: balance resource, for example `ВНаличииОстаток`;
- metric label: `Остаток`;
- optional filter role: `warehouse_type`;
- optional filter field: retail-store field path, for example
  `Склад.ТипСклада`;
- limit: `1`.

Set `Fields confirmed` only after checking the fields in Metadata Explorer or
verified XML metadata.

## 3. Configure Calculation

The form creates a `top_n_by_metric` calculation:

```text
group by product
measure = sum(stock balance)
filter = warehouse type equals retail store
sort = stock balance desc
limit = 1
```

Do not write a raw query unless advanced mode is intentionally enabled and the
query passes all validation gates.

## 4. Preview Query

Run preview. The query should:

- start with `ВЫБРАТЬ`;
- use the confirmed balance source;
- aggregate by product;
- sort the sum descending;
- preserve the retail warehouse filter.

If the preview uses an unconfirmed field or a wrong source, return to Metadata
Explorer and fix the draft.

## 5. Smoke Test

Run MCP smoke. Inspect the sample row and confirm that the product and quantity
match the business question.

## 6. Publish Candidate

Approve and publish the draft as a candidate skill. The candidate is still not
runtime-active by default.

## 7. Regression And Promotion

Create or select a regression case for the same question, run regression replay,
then promote the candidate to `verified`.

Only after this step can the agent use the skill in normal planning.
