# Tutorial: Top Stock Skill

This example creates a reusable skill for the question:

```text
Покажи какого товара больше всего в розничном магазине?
```

## 1. Find Data Sources

Use Metadata Explorer to find the stock balance register. In many trade
configurations this will be an accumulation register with product, warehouse,
and quantity fields.

Example target source:

```text
РегистрНакопления.ТоварыНаСкладах.Остатки()
```

Then find the warehouse catalog and the field that identifies a retail store.

## 2. Create Draft

Create a HumanSkillDraft with:

- title: `Товар с максимальным остатком в розничных магазинах`;
- example question: `Покажи какого товара больше всего в розничном магазине?`;
- source: stock balance register;
- product field role;
- warehouse field role;
- stock balance measure role;
- warehouse type filter role.

## 3. Configure Calculation

Use a `top_n_by_metric` calculation:

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
