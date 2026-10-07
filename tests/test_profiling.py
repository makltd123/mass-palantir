"""Профилирование и FK-детекция."""

import ontology_builder_v3 as ob


def _profiles(data_dir):
    tables = ob.discover_tables(data_dir)
    all_data = {name: ob.read_csv(path) for name, path in tables.items()}
    return ob.profile_all_columns(all_data, verbose=False)


def test_empty_table_does_not_crash():
    profiles = ob.profile_all_columns({"empty": []}, verbose=False)
    assert profiles["empty"] == {}


def test_headers_of_empty_rows():
    assert ob.headers_of([]) == []
    assert ob.headers_of([{"a": 1, "b": 2}]) == ["a", "b"]


def test_sequential_int_primary_key_detected(dirty_dir):
    profiles = _profiles(dirty_dir)
    assert profiles["customers"]["f_17"]["is_sequential_int"] is True
    assert profiles["customers"]["f_17"]["is_candidate_key"] is True


def test_renamed_foreign_keys_point_at_right_table(dirty_dir):
    """ref_9 → customers, item_ref → inventory, несмотря на бессмысленные имена."""
    profiles = _profiles(dirty_dir)
    top = profiles["orders"]["ref_9"]["fk_matches"][0]
    assert (top["table"], top["column"]) == ("customers", "f_17")
    top = profiles["order_items"]["item_ref"]["fk_matches"][0]
    assert (top["table"], top["column"]) == ("inventory", "sku_code")


def test_measure_column_is_not_a_foreign_key(dirty_dir):
    """Регрессия: quantity (значения 1..N) раньше «ссылался» на любой id."""
    profiles = _profiles(dirty_dir)
    assert profiles["order_items"]["quantity"]["fk_matches"] == []


def test_primary_key_is_not_reported_as_foreign_key(dirty_dir):
    profiles = _profiles(dirty_dir)
    assert profiles["customers"]["f_17"]["fk_matches"] == []


def test_junk_columns_flagged_and_keys_rescued(dirty_dir):
    profiles = _profiles(dirty_dir)
    assert profiles["customers"]["flag_2"]["likely_junk"] is True
    assert profiles["orders"]["status_old_v1"]["likely_junk"] is True
    # Короткие числовые FK раньше попадали в мусор и выбрасывались из графа.
    assert profiles["inventory"]["category_id"]["likely_junk"] is False
    assert profiles["inventory"]["warehouse_id"]["likely_junk"] is False


def test_is_date_and_is_numeric_helpers():
    assert ob._is_date("2024-01-31")
    assert ob._is_date("31.01.2024")
    assert not ob._is_date("31/01/2024")
    assert not ob._is_date(None)
    assert ob._is_numeric("12.5")
    assert not ob._is_numeric("abc")
