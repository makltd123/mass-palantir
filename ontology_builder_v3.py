"""
Прототип v3: data profiling + двухшаговые дубли + улучшенная классификация.
Решает проблемы v2: криптические ключи классифицировались как мусор,
дубли не найдены, мусорные столбцы не исключены.
"""

import csv
import json
import os
import re
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher

# ── Конфигурация ──────────────────────────────────────────────
CSV_DIR = os.path.dirname(os.path.abspath(__file__))
STOCK_THRESHOLD = 10
GRAPH_FILE = os.path.join(CSV_DIR, "ontology_v3_graph.json")
SAMPLE_ROWS = 20

CSV_FILES = {
    "customers":           os.path.join(CSV_DIR, "customers.csv"),
    "contacts":            os.path.join(CSV_DIR, "contacts.csv"),
    "product_categories":  os.path.join(CSV_DIR, "product_categories.csv"),
    "inventory":           os.path.join(CSV_DIR, "inventory.csv"),
    "warehouses":          os.path.join(CSV_DIR, "warehouses.csv"),
    "suppliers":           os.path.join(CSV_DIR, "suppliers.csv"),
    "supplier_contracts":  os.path.join(CSV_DIR, "supplier_contracts.csv"),
    "orders":              os.path.join(CSV_DIR, "orders.csv"),
    "order_items":         os.path.join(CSV_DIR, "order_items.csv"),
    "purchase_requests":   os.path.join(CSV_DIR, "purchase_requests.csv"),
}

ANSWER_KEY = {
    "renamed_fields": {
        "customers.id":       "поле id",
        "orders.customer_id":         "поле customer_id",
        "inventory.id":   "поле id",
        "order_items.inventory_id": "поле inventory_id",
    },
    "duplicate_customers": [],
    "junk_columns": [],
    "similar_products_not_to_merge": [],
}


# ── Утилиты ───────────────────────────────────────────────────
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def call_llm(prompt, label="LLM"):
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    MISTRAL_MODEL = "mistral-small-latest"
    try:
        if not MISTRAL_API_KEY:
            raise RuntimeError("не задана переменная MISTRAL_API_KEY")
        from mistralai.client import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        text = response.choices[0].message.content
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        print(f"[{label}] Ответ от Mistral ({MISTRAL_MODEL})")
        return json.loads(text)
    except Exception as e:
        print(f"[{label}] Ошибка: {e}")
        return None


# ── Data Profiling ────────────────────────────────────────────
def profile_all_columns(all_data):
    """Анализирует каждый столбец: типы, кардинальность, паттерны, FK-связи."""
    print("\n" + "=" * 70)
    print("  DATA PROFILING: Анализ значений во всех столбцах")
    print("=" * 70)

    profiles = {}

    # Собираем все значения для FK-детекции
    all_values = {}  # {(table, col): set of values}
    for table_name, rows in all_data.items():
        for col in rows[0].keys():
            vals = {r[col] for r in rows if r[col]}
            all_values[(table_name, col)] = vals

    for table_name, rows in all_data.items():
        profiles[table_name] = {}
        for col in rows[0].keys():
            vals = [r[col] for r in rows]
            non_empty = [v for v in vals if v]
            unique = set(non_empty)
            total = len(vals)

            p = {
                "column": col,
                "table": table_name,
                "total_rows": total,
                "non_empty": len(non_empty),
                "empty": total - len(non_empty),
                "unique": len(unique),
                "cardinality_ratio": round(len(unique) / total, 3) if total > 0 else 0,
                "samples": list(unique)[:8],
            }

            # Определяем тип значений
            if non_empty:
                is_numeric = all(_is_numeric(v) for v in non_empty)
                is_date = all(_is_date(v) for v in non_empty)
                avg_len = sum(len(v) for v in non_empty) / len(non_empty)

                p["is_numeric"] = is_numeric
                p["is_date"] = is_date
                p["avg_length"] = round(avg_len, 1)
                p["is_sequential_int"] = False

                if is_numeric:
                    nums = sorted(set(int(v) for v in non_empty))
                    if len(nums) > 1:
                        p["is_sequential_int"] = (nums[-1] - nums[0] + 1 == len(nums))
                        p["numeric_range"] = f"{nums[0]}-{nums[-1]}"

                # Мусор-эвристика: все значения длины 1-2, мало уникальных
                p["likely_junk"] = (
                    avg_len <= 2
                    and len(unique) <= 5
                    and len(unique) <= total * 0.3
                )

                # FK-детекция: значения совпадают со значениями другой таблицы
                p["fk_matches"] = []
                my_vals = unique
                for (t2, c2), v2 in all_values.items():
                    if t2 == table_name and c2 == col:
                        continue
                    if not my_vals or not v2:
                        continue
                    overlap = my_vals & v2
                    if len(overlap) > 0 and len(overlap) >= len(my_vals) * 0.5:
                        p["fk_matches"].append({
                            "table": t2,
                            "column": c2,
                            "overlap": len(overlap),
                            "my_count": len(my_vals),
                            "their_count": len(v2),
                        })
                p["fk_matches"].sort(key=lambda x: x["overlap"], reverse=True)

            profiles[table_name][col] = p

    # Вывод
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
                flags.append(f"FK→{top['table']}.{top['column']}({top['overlap']}/{top['my_count']})")
            if p.get("is_date"):
                flags.append("DATE")
            if p["empty"] > 0:
                flags.append(f"EMPTY={p['empty']}")

            flag_str = " | ".join(flags) if flags else ""
            print(f"    {col:25s} unique={p['unique']:3d}/{p['total_rows']:3d}  "
                  f"card={p['cardinality_ratio']:.2f}  "
                  f"avg_len={p.get('avg_length', 0):5.1f}  {flag_str}")

    return profiles


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
        except ValueError:
            continue
    return False


# ── Этап 1: Извлечение схемы ─────────────────────────────────
def extract_schemas():
    print("\n" + "=" * 70)
    print("  ЭТАП 1: Извлечение схем из CSV-файлов")
    print("=" * 70)
    schemas = {}
    for name, path in CSV_FILES.items():
        rows = read_csv(path)
        headers = list(rows[0].keys()) if rows else []
        samples = rows[:SAMPLE_ROWS]
        schemas[name] = {
            "columns": headers,
            "row_count": len(rows),
            "sample_rows": samples,
        }
        print(f"  {name:25s}: {len(headers)} столбцов, {len(rows)} строк")
    return schemas


# ── Этап 1.5: Классификация столбцов с профилями ─────────────
def classify_columns(schemas, profiles):
    print("\n" + "=" * 70)
    print("  ЭТАП 1.5: Классификация столбцов (с data profiling)")
    print("=" * 70)

    # Формируем профили в текст для LLM
    profile_text = ""
    for table_name, cols in profiles.items():
        profile_text += f"\nТаблица: {table_name}\n"
        for col, p in cols.items():
            fk_info = ""
            if p.get("fk_matches"):
                top = p["fk_matches"][0]
                fk_info = f", FK-кандидат → {top['table']}.{top['column']} (совпадение {top['overlap']}/{top['my_count']})"
            seq = "YES" if p.get("is_sequential_int") else "no"
            junk_hint = "VEROJATNO_JUNK" if p.get("likely_junk") else ""
            date_hint = "DATE" if p.get("is_date") else ""
            profile_text += (
                f"  {col}: unique={p['unique']}/{p['total_rows']}, "
                f"cardinality={p['cardinality_ratio']}, "
                f"avg_len={p.get('avg_length', 0)}, "
                f"sequential_int={seq}{fk_info} {junk_hint} {date_hint}\n"
            )

    prompt = f"""Ты — аналитик данных. Перед тобой профили ВСЕХ столбцов 10 CSV-таблиц компании.

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

    result = call_llm(prompt, "Этап 1.5")
    if result is None:
        result = _fallback_classify(profiles)

    junk = [c for c in result["columns_analysis"] if c["classification"] == "junk"]
    keys = [c for c in result["columns_analysis"] if c["classification"] == "key"]
    business = [c for c in result["columns_analysis"] if c["classification"] == "business"]

    print(f"  Business: {len(business)}, Keys: {len(keys)}, Junk: {len(junk)}")
    for j in junk:
        print(f"    МУСОР: {j['table']}.{j['column']} — {j['reason']}")
    for k in keys:
        print(f"    КЛЮЧ:  {k['table']}.{k['column']} — {k['reason']}")

    result["junk_columns"] = [f"{j['table']}.{j['column']}" for j in junk]
    result["key_columns"] = [f"{k['table']}.{k['column']}" for k in keys]
    return result


def _fallback_classify(profiles):
    analysis = []
    for table_name, cols in profiles.items():
        for col, p in cols.items():
            if p.get("likely_junk"):
                cls = "junk"
                reason = "мало уникальных коротких значений"
            elif p.get("is_sequential_int"):
                cls = "key"
                reason = "последовательные целые числа"
            elif p.get("fk_matches"):
                cls = "key"
                top = p["fk_matches"][0]
                reason = f"совпадает с {top['table']}.{top['column']}"
            else:
                cls = "business"
                reason = "осмысленное поле"
            analysis.append({"table": table_name, "column": col, "classification": cls, "reason": reason})
    return {"columns_analysis": analysis}


# ── Этап 2: Построение графа сущностей ───────────────────────
def build_entity_graph(schemas, classification):
    print("\n" + "=" * 70)
    print("  ЭТАП 2: Построение графа сущностей")
    print("=" * 70)

    junk_set = set(classification.get("junk_columns", []))
    key_cols = set(classification.get("key_columns", []))

    filtered_schemas = {}
    for name, s in schemas.items():
        filtered_cols = [c for c in s["columns"] if f"{name}.{c}" not in junk_set]
        filtered_rows = []
        for row in s["sample_rows"]:
            filtered_rows.append({k: v for k, v in row.items() if f"{name}.{k}" not in junk_set})
        filtered_schemas[name] = {
            "columns": filtered_cols,
            "row_count": s["row_count"],
            "sample_rows": filtered_rows[:10],
        }

    # Добавляем информацию о ключах
    key_info = []
    for kc in sorted(key_cols):
        table, col = kc.split(".")
        if table in filtered_schemas and col in filtered_schemas[table]["columns"]:
            key_info.append(kc)

    schemas_text = json.dumps(filtered_schemas, ensure_ascii=False, indent=2)

    prompt = f"""Ты — аналитик данных. Перед тобой схемы и примеры строк из 10 CSV-таблиц.

СХЕМЫ:
{schemas_text}

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
          "is_key": true/false
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

    result = call_llm(prompt, "Этап 2")
    if result is None:
        result = {"entities": [], "relationships": [], "field_matches": []}

    print(f"  Сущностей: {len(result['entities'])}")
    for ent in result["entities"]:
        print(f"    - {ent['name']}: {len(ent['attributes'])} атрибутов")
    print(f"  Связей: {len(result['relationships'])}")
    print(f"  Совпадений полей: {len(result['field_matches'])}")

    return result


# ── Этап 2.5: Поиск дублей (двухшаговый) ────────────────────
def find_duplicates_v3(all_data):
    print("\n" + "=" * 70)
    print("  ЭТАП 2.5: Поиск дублей (двухшаговый)")
    print("=" * 70)

    customers = all_data["customers"]

    # ── Шаг 1: Автоматическая нормализация + fuzzy match ──
    print("  [Шаг 1] Нормализация + fuzzy matching...")

    def normalize_name(name):
        n = name.lower().strip()
        n = n.replace("«", '"').replace("»", '"')
        n = re.sub(r'\s+', ' ', n)
        # Убираем "ооо" в начале/конце
        n = re.sub(r'^ооо\s+', '', n)
        n = re.sub(r'\s+ооо$', '', n)
        n = n.strip('" ')
        return n

    normalized = []
    for row in customers:
        cid = row.get("f_17", row.get("id", ""))
        raw_name = row.get("company_name", "")
        norm = normalize_name(raw_name)
        normalized.append({
            "id": cid,
            "raw": raw_name,
            "normalized": norm,
            "city": row.get("city", ""),
            "email": row.get("email", ""),
        })

    # Pairwise fuzzy match
    candidate_pairs = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            a = normalized[i]
            b = normalized[j]

            # Сравниваем нормализованные имена
            name_ratio = SequenceMatcher(None, a["normalized"], b["normalized"]).ratio()

            # Совпадение email/email если оба непустые
            email_match = (a["email"] == b["email"] and a["email"] != "")

            # Совпадение города
            city_match = (a["city"] == b["city"] and a["city"] != "")

            # Общий скор
            score = name_ratio
            if email_match:
                score = max(score, 0.95)  # email совпадает — почти наверняка дубль
            if city_match and name_ratio > 0.7:
                score = max(score, 0.9)

            if score >= 0.85:
                candidate_pairs.append({
                    "id_a": int(a["id"]),
                    "id_b": int(b["id"]),
                    "name_a": a["raw"],
                    "name_b": b["raw"],
                    "name_ratio": round(name_ratio, 3),
                    "email_match": email_match,
                    "city_match": city_match,
                    "score": round(score, 3),
                })

    candidate_pairs.sort(key=lambda x: x["score"], reverse=True)

    print(f"  Кандидатов на дубли (score >= 0.85): {len(candidate_pairs)}")
    for cp in candidate_pairs[:10]:
        print(f"    id={cp['id_a']}↔{cp['id_b']}: score={cp['score']}, "
              f"name_ratio={cp['name_ratio']}, email={cp['email_match']}, "
              f"city={cp['city_match']}")
        print(f"      \"{cp['name_a']}\" vs \"{cp['name_b']}\"")

    # ── Шаг 2: LLM подтверждает кандидатов ──
    if candidate_pairs:
        print(f"\n  [Шаг 2] LLM проверяет {len(candidate_pairs)} кандидатов...")

        candidates_text = json.dumps(
            [{"id_a": c["id_a"], "id_b": c["id_b"],
              "name_a": c["name_a"], "name_b": c["name_b"],
              "name_ratio": c["name_ratio"],
              "email_match": c["email_match"],
              "city_match": c["city_match"],
              "score": c["score"]}
             for c in candidate_pairs],
            ensure_ascii=False, indent=2
        )

        prompt = f"""Ты — аналитик данных. Перед тобою пара клиентов, найденные автоматически как вероятные дубли.

{candidates_text}

ВАЖНО: Это ДУБЛИ — одна и та же компания, записанная по-разному:
- Разный регистр
- Разные кавычки (" vs « »)
- Добавлено/убрано "ООО" в начале или конце
- Опечатки (пропущена/лишняя буква)

Если email и город совпадают — это почти наверняка дубль, даже если название немного отличается из-за опечатки.

ЗАДАЧА: Для каждой пары определи — это дубль? (true/false). Будь АГРЕССИВЕН в поиске дублей.

ВЕРНИ валидный JSON:
{{
  "confirmed_duplicates": [
    {{
      "id_a": id1,
      "id_b": id2,
      "is_duplicate": true/false,
      "confidence": "high" | "medium" | "low",
      "reason": "обоснование"
    }}
  ]
}}"""

        llm_result = call_llm(prompt, "Этап 2.5-шаг2")
        if llm_result:
            confirmed = [d for d in llm_result.get("confirmed_duplicates", []) if d["is_duplicate"]]
        else:
            confirmed = []
    else:
        confirmed = []

    print(f"\n  Подтверждённых дублей: {len(confirmed)}")
    for d in confirmed:
        print(f"    id={d['id_a']}↔{d['id_b']}: {d.get('confidence', '?')} — {d.get('reason', '')}")

    return {
        "candidate_pairs": candidate_pairs,
        "confirmed_duplicates": confirmed,
    }


# ── Этап 3: Хранение ─────────────────────────────────────────
def store_results(graph, classification, duplicates):
    print("\n" + "=" * 70)
    print("  ЭТАП 3: Сохранение результатов")
    print("=" * 70)

    full_result = {
        "column_classification": classification,
        "entity_graph": graph,
        "duplicate_analysis": duplicates,
    }
    with open(GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(full_result, f, ensure_ascii=False, indent=2)
    print(f"  Сохранено в {GRAPH_FILE}")


# ── Этап 3.5: Нормализация дат ──────────────────────────────
def normalize_dates():
    print("\n" + "=" * 70)
    print("  ЭТАП 3.5: Нормализация дат в orders.csv")
    print("=" * 70)

    path = CSV_FILES["orders"]
    rows = read_csv(path)
    normalized = 0
    formats = defaultdict(int)

    for row in rows:
        raw = row["order_date"]
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                row["order_date"] = dt.strftime("%Y-%m-%d")
                formats[fmt] += 1
                if fmt == "%d.%m.%Y":
                    normalized += 1
                break
            except ValueError:
                continue

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Форматы: {dict(formats)}")
    print(f"  Конвертировано: {normalized} строк")


# ── Этап 4: Низкий остаток ───────────────────────────────────
def check_low_stock(graph):
    print("\n" + "=" * 70)
    print("  ЭТАП 4: Анализ остатков")
    print("=" * 70)

    inventory_data = read_csv(CSV_FILES["inventory"])
    orders_data = read_csv(CSV_FILES["orders"])
    order_items_data = read_csv(CSV_FILES["order_items"])
    warehouses_data = read_csv(CSV_FILES["warehouses"])

    inv_id_col = "id"
    oi_inv_col = "inventory_id"

    inv_map = {}
    for row in inventory_data:
        inv_map[row[inv_id_col]] = {
            "product_name": row.get("product_name", ""),
            "stock": int(row.get("stock_quantity", 0)),
            "warehouse_id": row.get("warehouse_id", ""),
        }

    wh_map = {w["id"]: w["warehouse_name"] for w in warehouses_data}

    item_orders = defaultdict(int)
    item_dates = defaultdict(list)
    for row in order_items_data:
        inv_id = row[oi_inv_col]
        qty = int(row.get("quantity", 0))
        item_orders[inv_id] += qty
        order_id = row.get("order_id", "")
        for o in orders_data:
            if o["id"] == order_id:
                try:
                    dt = datetime.strptime(o["order_date"], "%Y-%m-%d")
                    item_dates[inv_id].append(dt)
                except ValueError:
                    pass
                break

    results = []
    for inv_id, info in inv_map.items():
        stock = info["stock"]
        if stock >= STOCK_THRESHOLD:
            continue

        total = item_orders.get(inv_id, 0)
        dates = sorted(item_dates.get(inv_id, []))
        if len(dates) > 1:
            span = (dates[-1] - dates[0]).days + 1
            speed = total / span if span > 0 else 0
        elif dates:
            speed = total
        else:
            speed = 0
        days_left = stock / speed if speed > 0 else None
        warehouse = wh_map.get(info["warehouse_id"], "Неизвестный")

        results.append({
            "sku_code": inv_id,
            "product_name": info["product_name"],
            "warehouse": warehouse,
            "stock": stock,
            "total_ordered": total,
            "speed_per_day": round(speed, 2),
            "days_left": round(days_left, 1) if days_left else None,
        })

    return results


# ── Этап 5: Отчёт ────────────────────────────────────────────
def print_report(low_stock):
    print("\n" + "=" * 70)
    print("  ЭТАП 5: ОТЧЁТ")
    print("=" * 70)

    if not low_stock:
        print("\nВсе товары в достаточном количестве.\n")
        return

    for item in low_stock:
        print(f"\n--- {item['product_name']} (арт. {item['sku_code']}) ---")
        print(f"  Склад:            {item['warehouse']}")
        print(f"  Остаток:          {item['stock']} шт.")
        print(f"  Всего заказано:   {item['total_ordered']} шт.")
        print(f"  Скорость расхода: {item['speed_per_day']} шт./день")
        if item["days_left"] is not None:
            print(f"  До исчерпания:    ~{item['days_left']} дней")
            qty = max(item["total_ordered"], item["stock"] * 3)
            print(f"  >>> РЕКОМЕНДАЦИЯ: Заявка на {qty} шт.")
        else:
            print(f"  До исчерпания:    нет данных")


# ── Этап 6: Сверка ───────────────────────────────────────────
def validate(graph, classification, duplicates):
    print("\n" + "=" * 70)
    print("  ЭТАП 6: СВЕРКА С КЛЮЧОМ ОТВЕТОВ")
    print("=" * 70)

    checks = []

    # 6.1 Legacy-поля
    print("\n--- 6.1 Legacy-поля ---")
    renamed = ANSWER_KEY["renamed_fields"]
    matched_columns = set()
    for fm in graph.get("field_matches", []):
        for m in fm.get("matches", []):
            matched_columns.add(f"{m['table']}.{m['column']}")

    # Также проверяем через ключи из classification
    key_cols = set(classification.get("key_columns", []))
    all_identified = matched_columns | key_cols

    for legacy_key in renamed:
        table, col = legacy_key.split(".")
        found = legacy_key in all_identified
        status = "ПРОЙДЕНО" if found else "ПРОВАЛЕНО"
        checks.append({"test": f"Legacy-поле {legacy_key}", "status": status})
        print(f"  {legacy_key}: {'✓' if found else '✗'} ({status})")

    # 6.2 Дубли
    print("\n--- 6.2 Дубли клиентов ---")
    expected = {(d["original_id"], d["duplicate_id"]) for d in ANSWER_KEY["duplicate_customers"]}
    found = set()
    for d in duplicates.get("confirmed_duplicates", []):
        a, b = d["id_a"], d["id_b"]
        found.add((min(a, b), max(a, b)))

    tp = len(found & expected)
    fp = len(found - expected)
    fn = len(expected - found)
    precision = tp / (tp + fp) * 100 if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) > 0 else 0

    checks.append({"test": f"Дубли: {tp}/{len(expected)} найдено", "status": f"P={precision:.0f}% R={recall:.0f}%"})
    print(f"  Найдено: {tp}/{len(expected)}, False+: {fp}")
    print(f"  Precision: {precision:.0f}%, Recall: {recall:.0f}%")
    if found & expected:
        print(f"  Истинные: {found & expected}")
    if found - expected:
        print(f"  Ложные:   {found - expected}")
    if expected - found:
        print(f"  Пропущены: {expected - found}")

    # 6.3 Похожие товары
    print("\n--- 6.3 Похожие товары НЕ объединены ---")
    similar_check = True
    for pair in ANSWER_KEY["similar_products_not_to_merge"]:
        combined = f"{pair[0]} и {pair[1]}"
        for e in graph.get("entities", []):
            if combined.lower() in e.get("name", "").lower():
                similar_check = False
    status = "ПРОЙДЕНО" if similar_check else "ПРОВАЛЕНО"
    checks.append({"test": "Похожие товары НЕ объединены", "status": status})
    print(f"  {'✓' if similar_check else '✗'} ({status})")

    # 6.4 Мусорные столбцы (сопоставление по имени столбца, не по table.column)
    print("\n--- 6.4 Мусорные столбцы ---")
    junk_from_llm = set(classification.get("junk_columns", []))
    # Извлекаем только имена столбцов из LLM-ответа
    junk_col_names = {jc.split(".")[-1] for jc in junk_from_llm}
    for col in ANSWER_KEY["junk_columns"]:
        found_junk = col in junk_col_names
        status = "ПРОЙДЕНО" if found_junk else "ПРОВАЛЕНО"
        checks.append({"test": f"Мусор {col}", "status": status})
        print(f"  {col}: {'✓ исключён' if found_junk else '✗ НЕ исключён'} ({status})")

    # Итог
    total = len(checks)
    passed = sum(1 for c in checks if "ПРОЙДЕНО" in c["status"])
    print(f"\n{'=' * 70}")
    print(f"  ИТОГ: {passed}/{total} проверок пройдено")
    print(f"{'=' * 70}")

    return checks


# ── Главная функция ──────────────────────────────────────────
def main():
    print("=" * 70)
    print("  ПРОТОТИП v3: DATA PROFILING + ДВУХШАГОВЫЕ ДУБЛИ")
    print("=" * 70)

    # Этап 1
    schemas = extract_schemas()

    # Data Profiling (перед классификацией!)
    all_data = {}
    for name, path in CSV_FILES.items():
        all_data[name] = read_csv(path)
    profiles = profile_all_columns(all_data)

    # Этап 1.5 (с профилями)
    classification = classify_columns(schemas, profiles)

    # Этап 2
    graph = build_entity_graph(schemas, classification)

    # Этап 2.5 (двухшаговый)
    duplicates = find_duplicates_v3(all_data)

    # Этап 3
    store_results(graph, classification, duplicates)

    # Этап 3.5
    normalize_dates()

    # Этап 4
    low_stock = check_low_stock(graph)

    # Этап 5
    print_report(low_stock)

    # Этап 6
    checks = validate(graph, classification, duplicates)

    return checks


if __name__ == "__main__":
    main()
