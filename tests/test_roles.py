"""Разрешение ролей столбцов — на чистых и на «грязных» данных."""

import ontology_builder_v3 as ob


def _roles(data_dir):
    tables = ob.discover_tables(data_dir)
    all_data = {name: ob.read_csv(path) for name, path in tables.items()}
    return ob.resolve_roles(ob.profile_all_columns(all_data, verbose=False))


def test_roles_on_clean_data(clean_dir):
    roles = _roles(clean_dir)
    assert roles["customers"]["pk"] == "id"
    assert roles["inventory"]["pk"] == "id"
    assert roles["order_items"]["inventory_fk"] == "inventory_id"
    assert roles["orders"]["customers_fk"] == "customer_id"


def test_roles_on_dirty_data(dirty_dir):
    """Те же роли, но столбцы переименованы — именно здесь v3 падала с KeyError."""
    roles = _roles(dirty_dir)
    assert roles["customers"]["pk"] == "f_17"
    assert roles["inventory"]["pk"] == "sku_code"
    assert roles["order_items"]["inventory_fk"] == "item_ref"
    assert roles["orders"]["customers_fk"] == "ref_9"


def test_name_columns_resolved(dirty_dir):
    roles = _roles(dirty_dir)
    assert roles["customers"]["name"] == "company_name"
    assert roles["inventory"]["name"] == "product_name"
    assert roles["suppliers"]["name"] == "supplier_name"


def test_one_column_gets_one_fk_role(dirty_dir):
    """Столбец не должен считаться ссылкой сразу на несколько таблиц."""
    roles = _roles(dirty_dir)
    fk_values = [v for k, v in roles["order_items"].items() if k.endswith("_fk")]
    assert len(fk_values) == len(set(fk_values))
    assert "customers_fk" not in roles["order_items"]
