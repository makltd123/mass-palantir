"""
Прототип v3: data profiling + двухшаговые дубли + улучшенная классификация.

Строит онтологию компании из набора CSV-таблиц: профилирует столбцы,
находит ключи и внешние ключи, описывает сущности и связи (через LLM),
ищет дубли клиентов, нормализует даты и считает правило «низкий остаток».

Запуск:
    python ontology_builder_v3.py --data-dir .                # как раньше
    python ontology_builder_v3.py --data-dir ./tmp --no-llm   # только эвристики
    python ontology_builder_v3.py --stock-threshold 30        # порог остатка
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher

# ── Конфигурация ──────────────────────────────────────────────
DEFAULT_STOCK_THRESHOLD = 10
DEFAULT_GRAPH_NAME = "ontology_v3_graph.json"
ANSWER_KEY_NAME = "answer_key.json"
SAMPLE_ROWS = 20
DEFAULT_MODEL = "mistral-small-latest"

# Таблицы, которые нужны прикладным этапам (дубли, остатки).
# Если какой-то таблицы нет — этап пропускается, а не падает.
KNOWN_TABLES = [
    "customers",
    "contacts",
    "product_categories",
    "inventory",
    "warehouses",
    "suppliers",
    "supplier_contracts",
    "orders",
    "order_items",
    "purchase_requests",
]

# Подсказки имён для разрешения ролей столбцов. Это только подсказки:
# если ни одно имя не совпало, роль определяется по профилю данных.
ROLE_HINTS = {
    ("customers", "pk"): ["id", "f_17", "customer_id"],
    ("customers", "name"): ["company_name", "name"],
    ("inventory", "pk"): ["id", "sku_code", "sku"],
    ("inventory", "name"): ["product_name", "name"],
    ("orders", "pk"): ["id", "order_id"],
    ("orders", "customers_fk"): ["customer_id", "ref_9"],
    ("order_items", "pk"): ["id"],
    ("order_items", "orders_fk"): ["order_id"],
    ("order_items", "inventory_fk"): ["inventory_id", "item_ref", "sku_code"],
    ("suppliers", "pk"): ["id"],
    ("suppliers", "name"): ["supplier_name", "name"],
    ("warehouses", "pk"): ["id"],
    ("warehouses", "name"): ["warehouse_name", "name"],
}

# Пустой ключ ответов: используется, если answer_key.json рядом с данными нет.
# Раньше ключ был зашит в код и описывал чистые данные, из-за чего этап сверки
# «проходил» проверки, которых фактически не было.
EMPTY_ANSWER_KEY = {
    "renamed_fields": {},
    "duplicate_customers": [],
    "junk_columns": [],
    "similar_products_not_to_merge": [],
}

# Пороги поиска дублей.
DUP_CANDIDATE_SCORE = 0.85   # кандидат уходит на подтверждение
DUP_AUTO_CONFIRM = 0.93      # эвристика подтверждает сама, без LLM

# Пороги FK-детекции.
FK_CHILD_COVERAGE = 0.9      # доля значений дочернего столбца, найденных в родителе
FK_PARENT_COVERAGE = 0.5     # доля ключей родителя, использованных дочерним столбцом
FK_PARENT_COVERAGE_HINTED = 0.2  # то же, если имя столбца похоже на ссылку
FK_NAME_HINTS = ("_id", "id_", "_ref", "ref_", "_code", "code_", "sku", "item")
# Имена, которые почти всегда означают измеряемую величину, а не ссылку.
# Без этого списка `quantity` (значения 1..10) «ссылается» на любой мелкий id.
MEASURE_NAMES = (
    "quantity", "qty", "count", "amount", "price", "cost", "total", "sum",
    "stock", "capacity", "weight", "volume", "number", "num", "year", "month",
    "day", "rate", "discount", "percent", "score",
)


# ── Утилиты ───────────────────────────────────────────────────
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def headers_of(rows):
    """Заголовки таблицы. Пустая таблица больше не роняет пайплайн."""
    return list(rows[0].keys()) if rows else []


def discover_tables(data_dir):
    """Находит CSV-файлы в каталоге. Известные таблицы идут первыми."""
    found = {}
    for entry in sorted(os.listdir(data_dir)):
        if entry.lower().endswith(".csv"):
            found[os.path.splitext(entry)[0]] = os.path.join(data_dir, entry)
    ordered = {}
    for name in KNOWN_TABLES:
        if name in found:
            ordered[name] = found.pop(name)
    ordered.update(found)
    return ordered


def load_answer_key(data_dir):
    """Читает answer_key.json рядом с данными. Нет файла — нет проверок."""
    path = os.path.join(data_dir, ANSWER_KEY_NAME)
    if not os.path.exists(path):
        return dict(EMPTY_ANSWER_KEY), None
    try:
        with open(path, encoding="utf-8") as f:
            key = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [ключ ответов] не прочитан ({e}), проверки будут пропущены")
        return dict(EMPTY_ANSWER_KEY), None
    merged = dict(EMPTY_ANSWER_KEY)
    merged.update(key)
    return merged, path


def extract_json(text):
    """Достаёт JSON из ответа модели: снимает ```-обёртку, берёт {...}."""
    if not isinstance(text, str):
        raise ValueError("ответ модели не является текстом")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start:end + 1])


def _import_mistral():
    """Mistral SDK менял путь импорта между версиями — поддерживаем оба."""
    try:
        from mistralai import Mistral
        return Mistral
    except ImportError:
        from mistralai.client import Mistral
        return Mistral


def call_llm(prompt, label="LLM", model=DEFAULT_MODEL, enabled=True):
    """Запрос к Mistral. None означает «работаем на эвристике»."""
    if not enabled:
        print(f"[{label}] LLM отключена (--no-llm), используем эвристику")
        return None
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print(f"[{label}] MISTRAL_API_KEY не задан, используем эвристику")
        return None
    try:
        mistral_cls = _import_mistral()
        client = mistral_cls(api_key=api_key)
        response = client.chat.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = extract_json(response.choices[0].message.content)
        print(f"[{label}] Ответ от Mistral ({model})")
        return result
    except Exception as e:  # сеть, лимиты, невалидный JSON — всё в эвристику
        print(f"[{label}] Ошибка {type(e).__name__}: {e}")
        return None


def _is_numeric(v):
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False


def _is_date(v):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            datetime.strptime(v, fmt)
            return True
        except (ValueError, TypeError):
            continue
    return False


def _has_fk_name_hint(column, target_table):
    col = column.lower()
    if any(h in col for h in FK_NAME_HINTS):
        return True
    stem = target_table.lower().rstrip("s")
    return bool(stem) and stem in col


# ── Data Profiling ────────────────────────────────────────────
def profile_all_columns(all_data, verbose=True):
    """Анализирует каждый столбец: типы, кардинальность, паттерны, FK-связи."""
    if verbose:
        print("\n" + "=" * 70)
        print("  DATA PROFILING: Анализ значений во всех столбцах")
        print("=" * 70)

    profiles = {}
    all_values = {}  # {(table, col): set(значений)}

    for table_name, rows in all_data.items():
        profiles[table_name] = {}
        for col in headers_of(rows):
            vals = [r.get(col) or "" for r in rows]
            non_empty = [v for v in vals if v]
            unique = set(non_empty)
            total = len(vals)
            all_values[(table_name, col)] = unique

            p = {
                "column": col,
                "table": table_name,
                "total_rows": total,
                "non_empty": len(non_empty),
                "empty": total - len(non_empty),
                "unique": len(unique),
                "cardinality_ratio": round(len(unique) / total, 3) if total else 0,
                "samples": sorted(unique)[:8],
                "is_numeric": False,
                "is_date": False,
                "avg_length": 0,
                "is_sequential_int": False,
                "likely_junk": False,
                "is_candidate_key": False,
                "fk_matches": [],
            }

            if non_empty:
                p["is_numeric"] = all(_is_numeric(v) for v in non_empty)
                p["is_date"] = all(_is_date(v) for v in non_empty)
                avg_len = sum(len(v) for v in non_empty) / len(non_empty)
                p["avg_length"] = round(avg_len, 1)

                if p["is_numeric"]:
                    try:
                        nums = sorted({int(float(v)) for v in non_empty})
                    except (ValueError, OverflowError):
                        nums = []
                    if len(nums) > 1:
                        p["is_sequential_int"] = (nums[-1] - nums[0] + 1 == len(nums))
                        p["numeric_range"] = f"{nums[0]}-{nums[-1]}"

                # Мусор-эвристика: все значения длины 1-2, мало уникальных
                p["likely_junk"] = (
                    avg_len <= 2
                    and len(unique) <= 5
                    and len(unique) <= total * 0.3
                )
                # Столбец-кандидат в ключи: заполнен и уникален
                p["is_candidate_key"] = (
                    len(unique) == len(non_empty) and len(non_empty) == total and total > 1
                )

            profiles[table_name][col] = p

    _detect_foreign_keys(profiles, all_values)
    _refine_junk_flags(profiles)

    if verbose:
        _print_profiles(profiles)
    return profiles


def _refine_junk_flags(profiles):
    """Снимает метку «мусор» со столбцов, которые оказались ключами.

    Короткий числовой FK (category_id, warehouse_id) попадал под мусор-эвристику
    и выбрасывался из графа вместе с настоящим мусором (flag_2, status_old_v1).
    """
    for cols in profiles.values():
        for col, p in cols.items():
            if not p["likely_junk"]:
                continue
            looks_like_key = bool(p["fk_matches"]) or any(
                h in col.lower() for h in FK_NAME_HINTS)
            if looks_like_key:
                p["likely_junk"] = False
                p["junk_rescued_as_key"] = True


def _is_measure_name(column):
    col = column.lower()
    return any(m in col for m in MEASURE_NAMES)


def _detect_foreign_keys(profiles, all_values):
    """FK-кандидаты по пересечению значений — с защитой от ложных срабатываний.

    Раньше условие было «пересечение >= 50% своих значений», из-за чего любой
    короткий числовой столбец (quantity) «ссылался» на любой id. Теперь нужно:
      * родитель — кандидат в ключи (уникален и заполнен);
      * дочерний столбец покрыт родителем почти целиком (FK_CHILD_COVERAGE);
      * дочерний столбец использует существенную долю ключей родителя,
        иначе это просто совпадение диапазонов чисел;
      * совпадают типы (числа с числами, строки со строками);
      * сам первичный ключ таблицы не объявляется внешним ключом;
      * столбцы-величины (quantity, price, ...) без намёка в имени не считаются
        ссылками, даже если их диапазон вложен в диапазон чужих id;
      * ссылка внутри своей же таблицы рассматривается последней.
    """
    candidate_keys = {
        (t, c) for t, cols in profiles.items()
        for c, p in cols.items() if p["is_candidate_key"]
    }
    primary_keys = {}
    for table, cols in profiles.items():
        pk = _guess_primary_key(cols)
        if pk:
            primary_keys[table] = pk

    for table, cols in profiles.items():
        for col, p in cols.items():
            child_vals = all_values.get((table, col), set())
            if len(child_vals) < 2:
                continue
            if primary_keys.get(table) == col:
                continue  # это PK таблицы, а не ссылка

            matches = []
            for (t2, c2), parent_vals in all_values.items():
                if (t2, c2) == (table, col) or (t2, c2) not in candidate_keys:
                    continue
                if not parent_vals:
                    continue
                parent_profile = profiles[t2][c2]
                if parent_profile["is_numeric"] != p["is_numeric"]:
                    continue
                overlap = child_vals & parent_vals
                if not overlap:
                    continue
                child_cov = len(overlap) / len(child_vals)
                parent_cov = len(overlap) / len(parent_vals)
                if child_cov < FK_CHILD_COVERAGE:
                    continue
                hinted = _has_fk_name_hint(col, t2)
                if not hinted and _is_measure_name(col):
                    continue
                min_parent_cov = FK_PARENT_COVERAGE_HINTED if hinted else FK_PARENT_COVERAGE
                if parent_cov < min_parent_cov:
                    continue
                matches.append({
                    "same_table": t2 == table,
                    "table": t2,
                    "column": c2,
                    "overlap": len(overlap),
                    "my_count": len(child_vals),
                    "their_count": len(parent_vals),
                    "child_coverage": round(child_cov, 3),
                    "parent_coverage": round(parent_cov, 3),
                    "name_hint": hinted,
                })

            # Лучший кандидат — самый «плотный»: использует больше ключей родителя.
            matches.sort(key=lambda m: (not m["same_table"], m["parent_coverage"],
                                        m["name_hint"], -m["their_count"]),
                         reverse=True)
            p["fk_matches"] = matches


def _guess_primary_key(cols):
    """PK таблицы: уникальный заполненный столбец, лучше всего — последовательный int."""
    best = None
    for col, p in cols.items():
        if not p["is_candidate_key"]:
            continue
        score = (
            2 if p["is_sequential_int"] else 0,
            1 if col.lower() in ("id", "pk") else 0,
            1 if p["is_numeric"] else 0,
        )
        if best is None or score > best[1]:
            best = (col, score)
    return best[0] if best else None


def _print_profiles(profiles):
    for table_name, cols in profiles.items():
        print(f"\n  {table_name}:")
        for col, p in cols.items():
            flags = []
            if p.get("is_sequential_int"):
                flags.append("SEQ_INT")
            if p.get("likely_junk"):
                flags.append("LIKELY_JUNK")
            if p.get("fk_matches"):
                top = p["fk_matches"][0]
                flags.append(
                    f"FK→{top['table']}.{top['column']}"
                    f"({top['overlap']}/{top['my_count']}, "
                    f"ключей родителя {top['parent_coverage']})"
                )
            if p.get("is_date"):
                flags.append("DATE")
            if p["empty"] > 0:
                flags.append(f"EMPTY={p['empty']}")
            flag_str = " | ".join(flags)
            print(f"    {col:25s} unique={p['unique']:3d}/{p['total_rows']:3d}  "
                  f"card={p['cardinality_ratio']:.2f}  "
                  f"avg_len={p.get('avg_length', 0):5.1f}  {flag_str}")


# ── Разрешение ролей столбцов ────────────────────────────────
def resolve_roles(profiles):
    """Определяет, какой столбец играет какую роль в каждой таблице.

    Это заменяет жёстко прописанные имена ('id', 'inventory_id'), из-за которых
    v3 падала с KeyError на «грязных» данных (там те же поля называются
    'sku_code' и 'item_ref'), а v2 — на чистых.
    """
    roles = {}
    for table, cols in profiles.items():
        table_roles = {}
        pk = _pick_by_hint(table, "pk", cols) or _guess_primary_key(cols)
        if pk:
            table_roles["pk"] = pk
        name_col = _pick_by_hint(table, "name", cols) or _guess_name_column(cols, pk)
        if name_col:
            table_roles["name"] = name_col
        roles[table] = table_roles

    # Внешние ключи: у каждого столбца берём только ЛУЧШЕГО кандидата,
    # иначе один столбец получал роль ссылки сразу на несколько таблиц.
    for table, cols in profiles.items():
        pk = roles[table].get("pk")
        for col, p in cols.items():
            if col == pk:
                continue
            matches = [m for m in (p.get("fk_matches") or []) if m["table"] != table]
            if not matches:
                continue
            best = matches[0]
            role = f"{best['table']}_fk"
            current = roles[table].get(role)
            if current is None:
                roles[table][role] = col
            else:
                current_cov = max(
                    (m["parent_coverage"] for m in cols[current].get("fk_matches") or []
                     if m["table"] == best["table"]), default=-1)
                if best["parent_coverage"] > current_cov:
                    roles[table][role] = col

    # Подсказки по именам важнее эвристики, если столбец действительно есть.
    for table, cols in profiles.items():
        for (hint_table, role), candidates in ROLE_HINTS.items():
            if hint_table != table or not role.endswith("_fk"):
                continue
            for candidate in candidates:
                if candidate in cols and candidate != roles[table].get("pk"):
                    roles[table][role] = candidate
                    break
    return roles


def _pick_by_hint(table, role, cols):
    for candidate in ROLE_HINTS.get((table, role), []):
        if candidate in cols:
            return candidate
    return None


NAME_HINTS = ("name", "title", "наименование", "название")


def _guess_name_column(cols, pk):
    """Столбец-название: сначала по имени, иначе самый «длинный» текстовый."""
    best = None
    for col, p in cols.items():
        if col == pk or p["is_numeric"] or p["is_date"] or p["likely_junk"]:
            continue
        by_name = any(h in col.lower() for h in NAME_HINTS)
        cand = (by_name, p["avg_length"])
        if best is None or cand > best[1]:
            best = (col, cand)
    return best[0] if best else None


# ── Этап 1: Извлечение схемы ─────────────────────────────────
def extract_schemas(csv_files):
    print("\n" + "=" * 70)
    print("  ЭТАП 1: Извлечение схем из CSV-файлов")
    print("=" * 70)
    schemas = {}
    for name, path in csv_files.items():
        rows = read_csv(path)
        schemas[name] = {
            "columns": headers_of(rows),
            "row_count": len(rows),
            "sample_rows": rows[:SAMPLE_ROWS],
        }
        print(f"  {name:25s}: {len(schemas[name]['columns'])} столбцов, {len(rows)} строк")
        if not rows:
            print(f"  {' ':25s}  (таблица пустая — этапы по ней будут пропущены)")
    return schemas


# ── Этап 1.5: Классификация столбцов с профилями ─────────────
def classify_columns(profiles, llm_enabled=True, model=DEFAULT_MODEL):
    print("\n" + "=" * 70)
    print("  ЭТАП 1.5: Классификация столбцов (с data profiling)")
    print("=" * 70)

    profile_text = ""
    for table_name, cols in profiles.items():
        profile_text += f"\nТаблица: {table_name}\n"
        for col, p in cols.items():
            fk_info = ""
            if p.get("fk_matches"):
                top = p["fk_matches"][0]
                fk_info = (f", FK-кандидат → {top['table']}.{top['column']} "
                           f"(совпадение {top['overlap']}/{top['my_count']})")
            seq = "YES" if p.get("is_sequential_int") else "no"
            junk_hint = "VEROJATNO_JUNK" if p.get("likely_junk") else ""
            date_hint = "DATE" if p.get("is_date") else ""
            profile_text += (
                f"  {col}: unique={p['unique']}/{p['total_rows']}, "
                f"cardinality={p['cardinality_ratio']}, "
                f"avg_len={p.get('avg_length', 0)}, "
                f"sequential_int={seq}{fk_info} {junk_hint} {date_hint}\n"
            )

    prompt = f"""Ты — аналитик данных. Перед тобой профили ВСЕХ столбцов CSV-таблиц компании.

ПРОФИЛИ СТОЛБЦОВ:
{profile_text}

ВАЖНЫЙ КОНТЕКСТ:
- "sequential_int=YES" означает что столбец содержит последовательные целые числа (1,2,3...) — это скорее всего ПЕРВИЧНЫЙ КЛЮЧ, а НЕ мусор.
- "FK→таблица.столбец" означает что значения этого столбца совпадают со значениями в другой таблице — это ВНЕШНИЙ КЛЮЧ.
- Даже если название столбца бессмысленное (f_17, ref_9, sku_code, item_ref), данные в нём могут быть ключами.
- "VEROJATNO_JUNK" — столбец содержит мало уникальных коротких значений (1-2 символа), возможно мусор.
- "DATE" — столбец содержит даты.

ЗАДАЧА: Для КАЖДОГО столбца определи:
1. business — осмысленное бизнес-поле
2. key — идентификатор/ключ (первичный или внешний), даже если название бессмысленное
3. junk — мусорный/служебный столбец

ВЕРНИ ТОЛЬКО валидный JSON:
{{
  "columns_analysis": [
    {{
      "table": "таблица",
      "column": "столбец",
      "classification": "business" | "key" | "junk",
      "reason": "обоснование с опорой на профиль"
    }}
  ]
}}"""

    result = call_llm(prompt, "Этап 1.5", model=model, enabled=llm_enabled)
    if not isinstance(result, dict) or "columns_analysis" not in result:
        if result is not None:
            print("  [Этап 1.5] ответ модели без columns_analysis — эвристика")
        result = _fallback_classify(profiles)
        result["source"] = "heuristic"
    else:
        result["source"] = "llm"

    analysis = [c for c in result["columns_analysis"]
                if isinstance(c, dict) and {"table", "column", "classification"} <= set(c)]
    result["columns_analysis"] = analysis

    junk = [c for c in analysis if c["classification"] == "junk"]
    keys = [c for c in analysis if c["classification"] == "key"]
    business = [c for c in analysis if c["classification"] == "business"]

    print(f"  Источник: {result['source']}")
    print(f"  Business: {len(business)}, Keys: {len(keys)}, Junk: {len(junk)}")
    for j in junk:
        print(f"    МУСОР: {j['table']}.{j['column']} — {j.get('reason', '')}")
    for k in keys:
        print(f"    КЛЮЧ:  {k['table']}.{k['column']} — {k.get('reason', '')}")

    result["junk_columns"] = [f"{j['table']}.{j['column']}" for j in junk]
    result["key_columns"] = [f"{k['table']}.{k['column']}" for k in keys]
    return result


def _fallback_classify(profiles):
    analysis = []
    for table_name, cols in profiles.items():
        for col, p in cols.items():
            if p.get("likely_junk"):
                cls, reason = "junk", "мало уникальных коротких значений"
            elif p.get("is_sequential_int") and p.get("is_candidate_key"):
                cls, reason = "key", "последовательные целые числа, уникальны"
            elif p.get("fk_matches"):
                top = p["fk_matches"][0]
                cls, reason = "key", f"совпадает с {top['table']}.{top['column']}"
            else:
                cls, reason = "business", "осмысленное поле"
            analysis.append({"table": table_name, "column": col,
                             "classification": cls, "reason": reason})
    return {"columns_analysis": analysis}


# ── Этап 2: Построение графа сущностей ───────────────────────
def build_entity_graph(schemas, classification, roles, llm_enabled=True, model=DEFAULT_MODEL):
    print("\n" + "=" * 70)
    print("  ЭТАП 2: Построение графа сущностей")
    print("=" * 70)

    junk_set = set(classification.get("junk_columns", []))
    key_cols = set(classification.get("key_columns", []))

    filtered_schemas = {}
    for name, s in schemas.items():
        filtered_schemas[name] = {
            "columns": [c for c in s["columns"] if f"{name}.{c}" not in junk_set],
            "row_count": s["row_count"],
            "sample_rows": [
                {k: v for k, v in row.items() if f"{name}.{k}" not in junk_set}
                for row in s["sample_rows"][:10]
            ],
        }

    key_info = [
        kc for kc in sorted(key_cols)
        if kc.split(".", 1)[0] in filtered_schemas
        and kc.split(".", 1)[1] in filtered_schemas[kc.split(".", 1)[0]]["columns"]
    ]

    prompt = f"""Ты — аналитик данных. Перед тобой схемы и примеры строк из CSV-таблиц.

СХЕМЫ:
{json.dumps(filtered_schemas, ensure_ascii=False, indent=2)}

КЛЮЧЕВЫЕ СТОЛБЦЫ (определены профилированием — это идентификаторы, а НЕ мусор):
{json.dumps(key_info, ensure_ascii=False)}

ЗАДАЧА:
1. Определи сущности (Клиент, Контакт, Заказ и т.д.).
2. Определи связи между сущностями.
3. Определи field_matches — какие столбцы в разных таблицах означают одно и то же.

ВЕРНИ валидный JSON:
{{
  "entities": [
    {{
      "name": "Сущность",
      "description": "что это",
      "attributes": [
        {{
          "field_name": "нормализованное_имя",
          "source_tables": ["таблица"],
          "source_columns": ["столбец"],
          "description": "что хранит",
          "is_key": true
        }}
      ]
    }}
  ],
  "relationships": [
    {{
      "from": "Сущность1",
      "to": "Сущность2",
      "type": "один_ко_многим",
      "join": {{"from_field": "поле1", "to_field": "поле2"}},
      "description": "описание"
    }}
  ],
  "field_matches": [
    {{
      "semantic_field": "описание",
      "matches": [{{"table": "таблица", "column": "столбец"}}]
    }}
  ]
}}"""

    result = call_llm(prompt, "Этап 2", model=model, enabled=llm_enabled)
    if not isinstance(result, dict) or "entities" not in result:
        if result is not None:
            print("  [Этап 2] ответ модели без entities — эвристика")
        result = _fallback_graph(schemas, roles, junk_set)
        result["source"] = "heuristic"
    else:
        result.setdefault("entities", [])
        result.setdefault("relationships", [])
        result.setdefault("field_matches", [])
        result["source"] = "llm"

    print(f"  Источник: {result['source']}")
    print(f"  Сущностей: {len(result['entities'])}")
    for ent in result["entities"]:
        print(f"    - {ent.get('name', '?')}: {len(ent.get('attributes', []))} атрибутов")
    print(f"  Связей: {len(result['relationships'])}")
    print(f"  Совпадений полей: {len(result['field_matches'])}")
    return result


def _fallback_graph(schemas, roles, junk_set):
    """Граф без LLM: таблица = сущность, FK из профиля = связь.

    Раньше без ключа этап возвращал пустой граф, и этап сверки не находил ни
    одного legacy-поля. Теперь связи и field_matches строятся по профилю.
    """
    entities, relationships, field_matches = [], [], []
    for table, s in schemas.items():
        table_roles = roles.get(table, {})
        attributes = []
        for col in s["columns"]:
            if f"{table}.{col}" in junk_set:
                continue
            is_key = col == table_roles.get("pk") or col in {
                v for k, v in table_roles.items() if k.endswith("_fk")
            }
            attributes.append({
                "field_name": col,
                "source_tables": [table],
                "source_columns": [col],
                "description": "ключ" if is_key else "бизнес-поле",
                "is_key": is_key,
            })
        entities.append({
            "name": table,
            "description": f"Сущность из таблицы {table} ({s['row_count']} строк)",
            "attributes": attributes,
        })

    for table, table_roles in roles.items():
        pk = table_roles.get("pk")
        for role, col in table_roles.items():
            if not role.endswith("_fk"):
                continue
            target = role[:-3]
            target_pk = roles.get(target, {}).get("pk")
            if not target_pk:
                continue
            relationships.append({
                "from": target,
                "to": table,
                "type": "один_ко_многим",
                "join": {"from_field": target_pk, "to_field": col},
                "description": f"{table}.{col} ссылается на {target}.{target_pk}",
            })
            field_matches.append({
                "semantic_field": f"идентификатор {target}",
                "matches": [
                    {"table": target, "column": target_pk},
                    {"table": table, "column": col},
                ],
            })
        if pk:
            field_matches.append({
                "semantic_field": f"первичный ключ {table}",
                "matches": [{"table": table, "column": pk}],
            })
    return {"entities": entities, "relationships": relationships,
            "field_matches": field_matches}


# ── Этап 2.5: Поиск дублей (двухшаговый) ────────────────────
def normalize_company_name(name):
    n = (name or "").lower().strip()
    n = n.replace("«", '"').replace("»", '"')
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"^ооо\s+", "", n)
    n = re.sub(r"\s+ооо$", "", n)
    return n.strip('" ')


def score_customer_pair(a, b):
    """Скор пары клиентов и его составляющие."""
    name_ratio = SequenceMatcher(None, a["normalized"], b["normalized"]).ratio()
    email_match = bool(a["email"]) and a["email"] == b["email"]
    city_match = bool(a["city"]) and a["city"] == b["city"]
    score = name_ratio
    if email_match:
        score = max(score, 0.95)      # email совпадает — почти наверняка дубль
    if city_match and name_ratio > 0.7:
        score = max(score, 0.9)
    return score, name_ratio, email_match, city_match


def find_duplicate_candidates(customers, roles):
    """Шаг 1: нормализация имён + нечёткое сравнение."""
    table_roles = roles.get("customers", {})
    id_col = table_roles.get("pk")
    name_col = table_roles.get("name")
    if not id_col or not name_col:
        return []

    normalized = [{
        "id": row.get(id_col, ""),
        "raw": row.get(name_col, ""),
        "normalized": normalize_company_name(row.get(name_col, "")),
        "city": row.get("city", ""),
        "email": row.get("email", ""),
    } for row in customers]

    pairs = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            a, b = normalized[i], normalized[j]
            score, name_ratio, email_match, city_match = score_customer_pair(a, b)
            if score >= DUP_CANDIDATE_SCORE:
                pairs.append({
                    "id_a": a["id"],
                    "id_b": b["id"],
                    "name_a": a["raw"],
                    "name_b": b["raw"],
                    "name_ratio": round(name_ratio, 3),
                    "email_match": email_match,
                    "city_match": city_match,
                    "score": round(score, 3),
                })
    pairs.sort(key=lambda x: x["score"], reverse=True)
    return pairs


def _confirm_duplicates_heuristically(candidate_pairs):
    """Подтверждение дублей без LLM.

    Без этого шага запуск без ключа находил правильных кандидатов, но возвращал
    пустой список подтверждённых — recall падал до 0%.
    """
    confirmed = []
    for c in candidate_pairs:
        strong = c["email_match"] and c["city_match"]
        if strong or c["score"] >= DUP_AUTO_CONFIRM:
            confirmed.append({
                "id_a": c["id_a"],
                "id_b": c["id_b"],
                "is_duplicate": True,
                "confidence": "high" if strong else "medium",
                "reason": ("совпадают email и город" if strong
                           else f"высокое сходство названий ({c['name_ratio']})"),
            })
    return confirmed


def find_duplicates_v3(all_data, roles, llm_enabled=True, model=DEFAULT_MODEL):
    print("\n" + "=" * 70)
    print("  ЭТАП 2.5: Поиск дублей (двухшаговый)")
    print("=" * 70)

    customers = all_data.get("customers") or []
    if not customers:
        print("  Таблицы customers нет или она пуста — этап пропущен")
        return {"candidate_pairs": [], "confirmed_duplicates": [], "source": "skipped"}

    print("  [Шаг 1] Нормализация + fuzzy matching...")
    candidate_pairs = find_duplicate_candidates(customers, roles)
    print(f"  Кандидатов на дубли (score >= {DUP_CANDIDATE_SCORE}): {len(candidate_pairs)}")
    for cp in candidate_pairs[:10]:
        print(f"    id={cp['id_a']}↔{cp['id_b']}: score={cp['score']}, "
              f"name_ratio={cp['name_ratio']}, email={cp['email_match']}, "
              f"city={cp['city_match']}")
        print(f"      \"{cp['name_a']}\" vs \"{cp['name_b']}\"")

    confirmed, source = [], "none"
    if candidate_pairs:
        print(f"\n  [Шаг 2] Проверка {len(candidate_pairs)} кандидатов...")
        prompt = f"""Ты — аналитик данных. Перед тобой пары клиентов, найденные автоматически как вероятные дубли.

{json.dumps(candidate_pairs, ensure_ascii=False, indent=2)}

ВАЖНО: Дубль — это одна и та же компания, записанная по-разному:
- Разный регистр
- Разные кавычки (" vs « »)
- Добавлено/убрано "ООО" в начале или конце
- Опечатки (пропущена/лишняя буква)

Если email и город совпадают — это почти наверняка дубль, даже если название немного отличается из-за опечатки.
Но РАЗНЫЕ компании с похожими названиями (разные фамилии в названии) дублями НЕ являются.

ЗАДАЧА: Для каждой пары определи — это дубль? (true/false).

ВЕРНИ валидный JSON:
{{
  "confirmed_duplicates": [
    {{
      "id_a": "id1",
      "id_b": "id2",
      "is_duplicate": true,
      "confidence": "high",
      "reason": "обоснование"
    }}
  ]
}}"""
        llm_result = call_llm(prompt, "Этап 2.5-шаг2", model=model, enabled=llm_enabled)
        if isinstance(llm_result, dict) and "confirmed_duplicates" in llm_result:
            confirmed = [d for d in llm_result["confirmed_duplicates"]
                         if isinstance(d, dict) and d.get("is_duplicate")]
            source = "llm"
        else:
            confirmed = _confirm_duplicates_heuristically(candidate_pairs)
            source = "heuristic"
        print(f"  Источник подтверждения: {source}")

    print(f"\n  Подтверждённых дублей: {len(confirmed)}")
    for d in confirmed:
        print(f"    id={d.get('id_a')}↔{d.get('id_b')}: "
              f"{d.get('confidence', '?')} — {d.get('reason', '')}")

    return {"candidate_pairs": candidate_pairs,
            "confirmed_duplicates": confirmed,
            "source": source}


# ── Этап 3: Хранение ─────────────────────────────────────────
def store_results(graph_file, graph, classification, duplicates, profiles=None):
    print("\n" + "=" * 70)
    print("  ЭТАП 3: Сохранение результатов")
    print("=" * 70)

    full_result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "column_classification": classification,
        "entity_graph": graph,
        "duplicate_analysis": duplicates,
    }
    if profiles is not None:
        full_result["profiles"] = profiles
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(full_result, f, ensure_ascii=False, indent=2)
    print(f"  Сохранено в {graph_file}")
    return full_result


# ── Этап 3.5: Нормализация дат ──────────────────────────────
def normalize_dates(path, date_column="order_date", backup=True):
    """Приводит даты к ГГГГ-ММ-ДД. Перед перезаписью делает .bak."""
    print("\n" + "=" * 70)
    print(f"  ЭТАП 3.5: Нормализация дат в {os.path.basename(path)}")
    print("=" * 70)

    rows = read_csv(path)
    if not rows or date_column not in rows[0]:
        print(f"  Столбца {date_column} нет — этап пропущен")
        return {"converted": 0, "formats": {}, "unparsed": []}

    normalized = 0
    formats = defaultdict(int)
    unparsed = []
    for row in rows:
        raw = row[date_column]
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                row[date_column] = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                formats[fmt] += 1
                if fmt == "%d.%m.%Y":
                    normalized += 1
                break
            except (ValueError, TypeError):
                continue
        else:
            unparsed.append(raw)

    if backup:
        shutil.copyfile(path, path + ".bak")
        print(f"  Резервная копия: {os.path.basename(path)}.bak")

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers_of(rows))
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Форматы: {dict(formats)}")
    print(f"  Конвертировано: {normalized} строк")
    if unparsed:
        print(f"  Не разобрано: {len(unparsed)} значений, например {unparsed[:3]}")
    return {"converted": normalized, "formats": dict(formats), "unparsed": unparsed}


# ── Этап 4: Низкий остаток ───────────────────────────────────
def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def check_low_stock(all_data, roles, threshold=DEFAULT_STOCK_THRESHOLD):
    """Товары с остатком ниже порога: скорость расхода и дни до исчерпания.

    Имена столбцов берутся из resolve_roles, а не зашиты в код: раньше этап
    падал с KeyError на «грязных» данных (inventory.sku_code вместо id).
    """
    print("\n" + "=" * 70)
    print("  ЭТАП 4: Анализ остатков")
    print("=" * 70)

    inventory = all_data.get("inventory") or []
    order_items = all_data.get("order_items") or []
    orders = all_data.get("orders") or []
    warehouses = all_data.get("warehouses") or []

    inv_roles = roles.get("inventory", {})
    oi_roles = roles.get("order_items", {})
    inv_pk = inv_roles.get("pk")
    inv_name = inv_roles.get("name")
    oi_inv_fk = oi_roles.get("inventory_fk")
    oi_order_fk = oi_roles.get("orders_fk")
    ord_pk = roles.get("orders", {}).get("pk")

    if not inventory or not inv_pk:
        print("  Таблицы inventory нет или не найден ключ — этап пропущен")
        return []
    if "stock_quantity" not in inventory[0]:
        print("  В inventory нет столбца stock_quantity — этап пропущен")
        return []
    if not oi_inv_fk:
        print("  Не найдена связь order_items → inventory, расход не посчитан")

    print(f"  Ключи: inventory.{inv_pk}, order_items.{oi_inv_fk or '—'}, "
          f"порог остатка = {threshold}")

    wh_roles = roles.get("warehouses", {})
    wh_map = {}
    if warehouses and wh_roles.get("pk"):
        wh_name = wh_roles.get("name") or wh_roles["pk"]
        wh_map = {w[wh_roles["pk"]]: w.get(wh_name, "") for w in warehouses}

    # Индекс дат заказов: раньше для каждой позиции делался линейный поиск по orders.
    order_dates = {}
    if orders and ord_pk:
        for o in orders:
            try:
                order_dates[o[ord_pk]] = datetime.strptime(o.get("order_date", ""), "%Y-%m-%d")
            except (ValueError, TypeError, KeyError):
                continue

    item_qty = defaultdict(int)
    item_dates = defaultdict(list)
    if oi_inv_fk:
        for row in order_items:
            inv_id = row.get(oi_inv_fk)
            if inv_id is None:
                continue
            item_qty[inv_id] += _to_int(row.get("quantity"))
            if oi_order_fk:
                dt = order_dates.get(row.get(oi_order_fk))
                if dt:
                    item_dates[inv_id].append(dt)

    results = []
    for row in inventory:
        inv_id = row.get(inv_pk)
        stock = _to_int(row.get("stock_quantity"))
        if stock >= threshold:
            continue

        total = item_qty.get(inv_id, 0)
        dates = sorted(item_dates.get(inv_id, []))
        if len(dates) > 1:
            span = (dates[-1] - dates[0]).days + 1
            speed = total / span if span > 0 else 0
        elif dates:
            speed = total
        else:
            speed = 0

        results.append({
            "sku_code": inv_id,
            "product_name": row.get(inv_name, "") if inv_name else "",
            "warehouse": wh_map.get(row.get("warehouse_id"), "Неизвестный"),
            "stock": stock,
            "total_ordered": total,
            "speed_per_day": round(speed, 2),
            "days_left": round(stock / speed, 1) if speed > 0 else None,
            "suggested_order": max(total, stock * 3) if speed > 0 else None,
        })

    results.sort(key=lambda r: (r["days_left"] is None, r["days_left"] or 0))
    print(f"  Позиций с остатком < {threshold}: {len(results)}")
    return results


# ── Этап 5: Отчёт ────────────────────────────────────────────
def print_report(low_stock, threshold=DEFAULT_STOCK_THRESHOLD):
    print("\n" + "=" * 70)
    print("  ЭТАП 5: ОТЧЁТ")
    print("=" * 70)

    if not low_stock:
        print(f"\nНет позиций с остатком меньше {threshold}. "
              f"Порог можно поднять: --stock-threshold N\n")
        return

    for item in low_stock:
        print(f"\n--- {item['product_name']} (арт. {item['sku_code']}) ---")
        print(f"  Склад:            {item['warehouse']}")
        print(f"  Остаток:          {item['stock']} шт.")
        print(f"  Всего заказано:   {item['total_ordered']} шт.")
        print(f"  Скорость расхода: {item['speed_per_day']} шт./день")
        if item["days_left"] is not None:
            print(f"  До исчерпания:    ~{item['days_left']} дней")
            print(f"  >>> РЕКОМЕНДАЦИЯ: Заявка на {item['suggested_order']} шт.")
        else:
            print("  До исчерпания:    нет данных (расхода по заказам не было)")


# ── Этап 6: Сверка ───────────────────────────────────────────
def validate(graph, classification, duplicates, answer_key):
    print("\n" + "=" * 70)
    print("  ЭТАП 6: СВЕРКА С КЛЮЧОМ ОТВЕТОВ")
    print("=" * 70)

    checks = []

    def add(test, passed, detail=""):
        checks.append({"test": test, "passed": bool(passed), "detail": detail})

    renamed = answer_key.get("renamed_fields") or {}
    expected_dups = answer_key.get("duplicate_customers") or []
    expected_junk = answer_key.get("junk_columns") or []
    expected_similar = answer_key.get("similar_products_not_to_merge") or []

    if not (renamed or expected_dups or expected_junk or expected_similar):
        print("\n  Ключ ответов пуст (нет answer_key.json) — сверять нечего.")
        print("  Сгенерируйте данные через generate_dirty_data.py, чтобы получить ключ.")
        return checks

    # 6.1 Legacy-поля
    print("\n--- 6.1 Legacy-поля ---")
    matched_columns = {
        f"{m['table']}.{m['column']}"
        for fm in graph.get("field_matches", [])
        for m in fm.get("matches", [])
        if isinstance(m, dict) and "table" in m and "column" in m
    }
    all_identified = matched_columns | set(classification.get("key_columns", []))
    for legacy_key in renamed:
        found = legacy_key in all_identified
        add(f"Legacy-поле {legacy_key}", found)
        print(f"  {legacy_key}: {'✓' if found else '✗'}")

    # 6.2 Дубли
    print("\n--- 6.2 Дубли клиентов ---")
    expected = {
        (str(d["original_id"]), str(d["duplicate_id"]))
        for d in expected_dups if isinstance(d, dict)
    }
    expected = {tuple(sorted(pair)) for pair in expected}
    found = {
        tuple(sorted((str(d.get("id_a")), str(d.get("id_b")))))
        for d in duplicates.get("confirmed_duplicates", [])
    }
    tp, fp, fn = len(found & expected), len(found - expected), len(expected - found)
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0.0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0.0
    print(f"  Найдено: {tp}/{len(expected)}, ложных: {fp}, пропущено: {fn}")
    print(f"  Precision: {precision:.0f}%, Recall: {recall:.0f}%")
    if found - expected:
        print(f"  Ложные:    {sorted(found - expected)}")
    if expected - found:
        print(f"  Пропущены: {sorted(expected - found)}")
    add(f"Дубли: найдено {tp}/{len(expected)}, ложных {fp}",
        fn == 0 and fp == 0,
        f"P={precision:.0f}% R={recall:.0f}%")

    # 6.3 Похожие товары не должны быть объединены
    print("\n--- 6.3 Похожие товары НЕ объединены ---")
    entity_names = " ".join(e.get("name", "") for e in graph.get("entities", [])).lower()
    similar_ok = True
    for pair in expected_similar:
        if len(pair) < 2:
            continue
        if f"{pair[0]} и {pair[1]}".lower() in entity_names:
            similar_ok = False
            print(f"  ✗ объединены: {pair[0]} и {pair[1]}")
    if similar_ok:
        print("  ✓ похожие товары не объединены")
    add("Похожие товары НЕ объединены", similar_ok)

    # 6.4 Мусорные столбцы
    print("\n--- 6.4 Мусорные столбцы ---")
    junk_col_names = {jc.split(".")[-1] for jc in classification.get("junk_columns", [])}
    for col in expected_junk:
        found_junk = col in junk_col_names
        add(f"Мусор {col}", found_junk)
        print(f"  {col}: {'✓ исключён' if found_junk else '✗ НЕ исключён'}")

    passed = sum(1 for c in checks if c["passed"])
    print(f"\n{'=' * 70}")
    print(f"  ИТОГ: {passed}/{len(checks)} проверок пройдено")
    print(f"{'=' * 70}")
    return checks


# ── Главная функция ──────────────────────────────────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Строит онтологию компании из CSV-таблиц.")
    parser.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)),
                        help="каталог с CSV-файлами (по умолчанию — каталог скрипта)")
    parser.add_argument("--output", default=None,
                        help=f"файл результата (по умолчанию {DEFAULT_GRAPH_NAME} в --data-dir)")
    parser.add_argument("--stock-threshold", type=int, default=DEFAULT_STOCK_THRESHOLD,
                        help=f"порог остатка для рекомендаций (по умолчанию {DEFAULT_STOCK_THRESHOLD})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="модель Mistral")
    parser.add_argument("--no-llm", action="store_true",
                        help="не обращаться к LLM, работать только на эвристиках")
    parser.add_argument("--no-write", action="store_true",
                        help="не перезаписывать CSV-файлы (не нормализовать даты)")
    parser.add_argument("--save-profiles", action="store_true",
                        help="сохранить профили столбцов в файл результата")
    return parser.parse_args(argv)


def run(args):
    data_dir = os.path.abspath(args.data_dir)
    if not os.path.isdir(data_dir):
        raise SystemExit(f"Каталог не найден: {data_dir}")

    csv_files = discover_tables(data_dir)
    if not csv_files:
        raise SystemExit(f"В каталоге {data_dir} нет CSV-файлов")

    graph_file = args.output or os.path.join(data_dir, DEFAULT_GRAPH_NAME)
    llm_enabled = not args.no_llm

    print("=" * 70)
    print("  ПРОТОТИП v3: DATA PROFILING + ДВУХШАГОВЫЕ ДУБЛИ")
    print("=" * 70)
    print(f"  Данные: {data_dir}")
    print(f"  Таблиц найдено: {len(csv_files)}")
    print(f"  LLM: {'включена' if llm_enabled else 'отключена'}")

    # Этап 1
    schemas = extract_schemas(csv_files)
    all_data = {name: read_csv(path) for name, path in csv_files.items()}

    # Профилирование и разрешение ролей столбцов
    profiles = profile_all_columns(all_data)
    roles = resolve_roles(profiles)
    print("\n  Роли столбцов:")
    for table, table_roles in roles.items():
        if table_roles:
            print(f"    {table}: " + ", ".join(f"{k}={v}" for k, v in sorted(table_roles.items())))

    # Этап 1.5
    classification = classify_columns(profiles, llm_enabled=llm_enabled, model=args.model)

    # Этап 2
    graph = build_entity_graph(schemas, classification, roles,
                               llm_enabled=llm_enabled, model=args.model)

    # Этап 2.5
    duplicates = find_duplicates_v3(all_data, roles,
                                    llm_enabled=llm_enabled, model=args.model)

    # Этап 3
    store_results(graph_file, graph, classification, duplicates,
                  profiles=profiles if args.save_profiles else None)

    # Этап 3.5
    if args.no_write:
        print("\n  ЭТАП 3.5 пропущен (--no-write)")
    elif "orders" in csv_files:
        normalize_dates(csv_files["orders"])
        all_data["orders"] = read_csv(csv_files["orders"])

    # Этапы 4-5
    low_stock = check_low_stock(all_data, roles, threshold=args.stock_threshold)
    print_report(low_stock, threshold=args.stock_threshold)

    # Этап 6
    answer_key, key_path = load_answer_key(data_dir)
    if key_path:
        print(f"\n  Ключ ответов: {key_path}")
    checks = validate(graph, classification, duplicates, answer_key)

    return {
        "profiles": profiles,
        "roles": roles,
        "classification": classification,
        "graph": graph,
        "duplicates": duplicates,
        "low_stock": low_stock,
        "checks": checks,
    }


def main(argv=None):
    result = run(parse_args(argv))
    failed = [c for c in result["checks"] if not c["passed"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
