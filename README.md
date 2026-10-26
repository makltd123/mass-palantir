# Mass Palantir

**English** | [Русский](README.ru.md)

A prototype that builds a company ontology from scattered CSV tables on its own. It finds entities (Customer, Order, Product, and so on), the relationships between them, and fields in different tables that mean the same thing even when they are named differently. The idea is similar to the Ontology in Palantir Foundry, but "for the masses": a few CSV files and an LLM instead of an implementation team.

The prompts, console output and synthetic data are in Russian.

## What v3 does

1. **Data profiling.** For every column it computes fill rate and share of unique values. It detects sequential integers (a sign of a primary key) and foreign keys by value overlap between tables, and flags columns that look like junk.
2. **Column classification.** An LLM labels each column as a business field, a key, or junk, based on the profile.
3. **Entity graph.** An LLM describes the entities, the relationships and the field matches across tables.
4. **Two-step customer deduplication.** First, name normalization and fuzzy matching (`difflib`); then the LLM confirms the candidates.
5. **Date normalization** in `orders.csv`: `DD.MM.YYYY` → `YYYY-MM-DD`.
6. **Low-stock rule.** For products with fewer than 10 units in stock it computes the consumption rate from orders and the days until stock runs out, and suggests a purchase quantity.
7. **Answer-key check.** Verifies the detected legacy fields, duplicates (precision and recall) and junk columns.

Without a Mistral key the script still runs, but on heuristics only: columns are classified from the profile, and the entity graph and duplicate confirmation are skipped.

## Data

The data is synthetic, generated with Faker (`ru_RU`). All company names, people, phone numbers and emails are made up. It is 10 tables of a machine-building company: `customers`, `contacts`, `product_categories`, `inventory`, `warehouses`, `suppliers`, `supplier_contracts`, `orders`, `order_items`, `purchase_requests`.

- `generate_realistic_data.py` — clean data. This is what is currently in the repository.
- `generate_dirty_data.py` — the same tables with typical real-world mess: renamed legacy keys (`f_17`, `ref_9`, `sku_code`, `item_ref`), duplicate customers, typos, mixed date formats, junk columns. Prints an answer key.

Both generators write to the same files, so each run overwrites the previous data.

## Versions

| File | What it is |
|---|---|
| `ontology_builder.py` | v1: the first prototype, on three tables with old field names (`client_ref`, `item_code`). It expects a data format that is no longer in the repository and is kept for history. |
| `ontology_builder_v2.py` | v2: 10 tables, dirty data, checked against the answer key from `generate_dirty_data.py`. |
| `ontology_builder_v3.py` | v3: adds data profiling, two-step deduplication, and heuristics for when the LLM is unavailable. Its answer key is set up for the clean data. |

Run results are in `ontology_graph.json` (v1), `ontology_v2_graph.json` and `ontology_v3_graph.json`. The saved v3 result comes from a run where the model did not respond: its entity graph is empty and the columns were classified by the heuristic.

## Running it

```powershell
pip install -r requirements.txt
$env:MISTRAL_API_KEY = "..."   # optional: without a key only the heuristics run
$env:PYTHONUTF8 = "1"          # so the ✓ and ✗ symbols print in the Windows console

python generate_realistic_data.py   # or generate_dirty_data.py
python ontology_builder_v3.py
```

`ontology_builder_v3.py` overwrites `orders.csv` (it normalizes dates) and `ontology_v3_graph.json`.

## Limitations

- Built for small tables: customers are compared pairwise, and sample rows from every table go to the LLM.
- The model's answer is parsed as JSON. If the model answers in another format, that stage falls back to the heuristic.

## License

[MIT](LICENSE)

---

Author: [Fedor Makovskiy](https://fedor.alqira.ru), AI developer. Services and projects with quality metrics: [fedor.alqira.ru](https://fedor.alqira.ru).
