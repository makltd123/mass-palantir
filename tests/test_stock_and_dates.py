"""Нормализация дат и правило «низкий остаток»."""

import csv
import os

import ontology_builder_v3 as ob


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_normalize_dates_converts_and_backs_up(tmp_path):
    path = tmp_path / "orders.csv"
    _write_csv(path, [
        {"id": "1", "order_date": "2024-02-02"},
        {"id": "2", "order_date": "15.03.2024"},
        {"id": "3", "order_date": "не дата"},
    ])
    result = ob.normalize_dates(str(path))

    assert result["converted"] == 1
    assert result["unparsed"] == ["не дата"]
    assert os.path.exists(str(path) + ".bak")  # исходник не потерян

    rows = ob.read_csv(str(path))
    assert [r["order_date"] for r in rows] == ["2024-02-02", "2024-03-15", "не дата"]


def test_normalize_dates_skips_table_without_column(tmp_path):
    path = tmp_path / "orders.csv"
    _write_csv(path, [{"id": "1", "status": "Закрыт"}])
    assert ob.normalize_dates(str(path))["converted"] == 0


def test_low_stock_uses_resolved_columns():
    """Имена столбцов «грязные» — этап обязан работать, а не падать с KeyError."""
    all_data = {
        "inventory": [
            {"sku_code": "1", "product_name": "Насос Н-1", "stock_quantity": "5",
             "warehouse_id": "1"},
            {"sku_code": "2", "product_name": "Насос Н-2", "stock_quantity": "500",
             "warehouse_id": "1"},
        ],
        "order_items": [
            {"id": "1", "order_id": "1", "item_ref": "1", "quantity": "10"},
            {"id": "2", "order_id": "2", "item_ref": "1", "quantity": "10"},
        ],
        "orders": [
            {"id": "1", "order_date": "2024-01-01"},
            {"id": "2", "order_date": "2024-01-11"},
        ],
        "warehouses": [{"id": "1", "warehouse_name": "Основной"}],
    }
    roles = {
        "inventory": {"pk": "sku_code", "name": "product_name"},
        "order_items": {"pk": "id", "inventory_fk": "item_ref", "orders_fk": "order_id"},
        "orders": {"pk": "id"},
        "warehouses": {"pk": "id", "name": "warehouse_name"},
    }
    result = ob.check_low_stock(all_data, roles, threshold=10)

    assert len(result) == 1
    item = result[0]
    assert item["sku_code"] == "1"
    assert item["total_ordered"] == 20
    assert item["speed_per_day"] == 1.82   # 20 шт. за 11 дней
    assert item["days_left"] == 2.8        # 5 / (20/11)
    assert item["warehouse"] == "Основной"


def test_low_stock_skips_missing_tables():
    assert ob.check_low_stock({}, {}, threshold=10) == []
    assert ob.check_low_stock({"inventory": [{"id": "1"}]}, {"inventory": {"pk": "id"}}) == []


def test_low_stock_handles_broken_quantities():
    all_data = {
        "inventory": [{"id": "1", "product_name": "X", "stock_quantity": "", "warehouse_id": ""}],
        "order_items": [{"id": "1", "inventory_id": "1", "quantity": "не число"}],
        "orders": [],
        "warehouses": [],
    }
    roles = {
        "inventory": {"pk": "id", "name": "product_name"},
        "order_items": {"pk": "id", "inventory_fk": "inventory_id"},
    }
    result = ob.check_low_stock(all_data, roles, threshold=10)
    assert result[0]["stock"] == 0
    assert result[0]["total_ordered"] == 0
    assert result[0]["days_left"] is None
