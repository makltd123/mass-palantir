# Mass Palantir

**English** | [Русский](README.ru.md)

A prototype that builds a company ontology from scattered CSV tables on its own. It finds entities (Customer, Order, Product, and so on), the relationships between them, and fields in different tables that mean the same thing even when they are named differently. The idea is similar to the Ontology in Palantir Foundry, but "for the masses": a few CSV files and an LLM instead of an implementation team.

The key property: column names are not treated as the source of truth. Keys and relationships are inferred from the values, so `f_17`, `ref_9`, `sku_code` and `item_ref` are recognised as identifiers just like `id` and `customer_id`.

The prompts, console output and synthetic data are in Russian.

## What v3 does

1. **Data profiling.** For every column it computes fill rate and share of unique values. It detects sequential integers (a sign of a primary key) and foreign keys by value overlap between tables, and flags columns that look like junk.
2. **Column role resolution.** It works out which column in each table is the primary key, the name and a foreign key. The downstream stages rely on this instead of hard-coded field names.
3. **Column classification.** An LLM labels each column as a business field, a key, or junk, based on the profile.
4. **Entity graph.** An LLM describes the entities, the relationships and the field matches across tables.
5. **Two-step customer deduplication.** First, name normalization and fuzzy matching (`difflib`); then candidates are confirmed either by the LLM or by a heuristic.
6. **Date normalization** in `orders.csv`: `DD.MM.YYYY` → `YYYY-MM-DD`. An `orders.csv.bak` copy is made before the file is rewritten.
7. **Low-stock rule.** For products below the stock threshold it computes the consumption rate from orders and the days until stock runs out, and suggests a purchase quantity.
8. **Answer-key check.** If an `answer_key.json` sits next to the data, it verifies the detected legacy fields, duplicates (precision and recall) and junk columns.

Without a Mistral key the script runs entirely on heuristics: columns are classified from the profile, the graph is built from the detected keys and relationships, and duplicates are confirmed by matching email and city. On the dirty data such a run passes all 8 checks — see [examples/run_dirty_no_llm.md](examples/run_dirty_no_llm.md).

## Data

The data is synthetic, generated with Faker (`ru_RU`). All company names, people, phone numbers and emails are made up. It is 10 tables of a machine-building company: `customers`, `contacts`, `product_categories`, `inventory`, `warehouses`, `suppliers`, `supplier_contracts`, `orders`, `order_items`, `purchase_requests`.

- `generate_realistic_data.py` — clean data. This is what is currently in the repository.
- `generate_dirty_data.py` — the same tables with typical real-world mess: renamed legacy keys (`f_17`, `ref_9`, `sku_code`, `item_ref`), duplicate customers, typos, mixed date formats, junk columns. It prints an answer key and saves it to `answer_key.json`.

Both generators accept `--out-dir`, so you can generate into a separate folder instead of overwriting the repository's files:

```bash
python generate_dirty_data.py --out-dir ./demo
```

## Versions

| File | What it is |
|---|---|
| `ontology_builder.py` | v1: the first prototype, on three tables with old field names (`client_ref`, `item_code`). It expects a data format that is no longer in the repository and is kept for history (excluded from linting). |
| `ontology_builder_v2.py` | v2: 10 tables, dirty data, checked against the answer key. It has no fallbacks without an API key, so it only passes part of the checks. |
| `ontology_builder_v3.py` | v3: the current version. Profiling, column role resolution, two-step deduplication, and heuristics for when the LLM is unavailable. |

Run results are in `ontology_graph.json` (v1), `ontology_v2_graph.json` and `ontology_v3_graph.json`.

## Running it

```bash
pip install -r requirements.txt          # mistralai only
pip install -r requirements-dev.txt      # + pandas, Faker, pytest, ruff

export MISTRAL_API_KEY="..."             # optional
export PYTHONUTF8=1                      # so ✓ and ✗ print in the Windows console

python generate_dirty_data.py --out-dir ./demo
python ontology_builder_v3.py --data-dir ./demo
```

In PowerShell, set variables as `$env:MISTRAL_API_KEY = "..."`.

### Command-line flags

| Flag | What it does |
|---|---|
| `--data-dir DIR` | folder with the CSV files (defaults to the script's folder) |
| `--output FILE` | where to save the result (defaults to `ontology_v3_graph.json` in `--data-dir`) |
| `--stock-threshold N` | stock threshold for recommendations (default 10) |
| `--model NAME` | Mistral model (default `mistral-small-latest`) |
| `--no-llm` | never call the LLM, run on heuristics only |
| `--no-write` | do not rewrite CSV files (skip date normalization) |
| `--save-profiles` | include the column profiles in the result file |

Exit code: `0` when every answer-key check passed (or there was nothing to check), `1` when at least one check failed. Handy for CI.

The script rewrites `orders.csv` during date normalization (leaving a `.bak` next to it) and the result file. With `--no-write` the CSVs are left alone.

Tables are discovered by the `.csv` extension in `--data-dir`, so you can drop in your own files. The applied stages only run when the tables they need are present: `customers` for deduplication, `inventory` and `order_items` for stock.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

The tests generate data into a temporary folder and never touch the repository's files. CI runs the same on Python 3.11, 3.12 and 3.13.

## Limitations and risks

- **Scale.** Built for small tables: customers are compared pairwise (O(n²)), FK detection walks every pair of columns, and sample rows from every table go to the LLM in a single prompt.
- **An FK heuristic does not prove a relationship.** Overlapping values are a hint, not proof: on surrogate integer keys the ranges overlap by chance. So the detector requires near-total inclusion of the child's values, a unique parent column, matching types, and a substantial share of the parent's keys being used; measure-like columns (`quantity`, `price`, `stock`, ...) without a naming hint are never treated as references. False positives are still possible — review the result.
- **Data goes to the LLM.** Sample rows end up in the prompts: company names, emails, phone numbers. On real data that means sending personal data to a third-party service — use `--no-llm` or a local model.
- **CSV content enters the prompt as text.** That opens the door to prompt injection: a row in the data can carry instructions for the model. The LLM stages survive a garbage response (they fall back to heuristics), but do not trust the graph on untrusted data.
- **The model's answer is parsed as JSON.** If the model answers in another format, that stage falls back to the heuristic.
- **The answer key only exists for the synthetic data.** On your own data there is nothing to verify: with no `answer_key.json`, the checks are skipped.

## License

[MIT](LICENSE)
