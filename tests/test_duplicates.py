"""Поиск дублей клиентов: эвристика без LLM должна давать P=R=100% на ключе."""

import json
import os

import ontology_builder_v3 as ob


def test_normalize_company_name():
    assert ob.normalize_company_name('ООО "Савин Пром"') == "савин пром"
    assert ob.normalize_company_name('«Савин Пром» ООО') == "савин пром"
    assert ob.normalize_company_name("  ООО   Савин  Пром ") == "савин пром"
    assert ob.normalize_company_name(None) == ""


def test_score_pair_email_match_outweighs_typo():
    a = {"normalized": "савин пром", "email": "x@y.z", "city": "Москва"}
    b = {"normalized": "савин пом", "email": "x@y.z", "city": "Москва"}
    score, name_ratio, email_match, city_match = ob.score_customer_pair(a, b)
    assert email_match and city_match
    assert score >= ob.DUP_AUTO_CONFIRM
    assert name_ratio < 1.0


def test_different_companies_are_not_auto_confirmed():
    """Куликова и Калашникова — разные компании, не дубли."""
    a = {"normalized": '"куликова инжиниринг"', "email": "a@a.a", "city": "Казань"}
    b = {"normalized": '"калашникова инжиниринг"', "email": "b@b.b", "city": "Омск"}
    score, _, _, _ = ob.score_customer_pair(a, b)
    confirmed = ob._confirm_duplicates_heuristically([{
        "id_a": "3", "id_b": "10", "score": round(score, 3),
        "name_ratio": round(score, 3), "email_match": False, "city_match": False,
    }])
    assert confirmed == []


def test_duplicates_match_answer_key_without_llm(dirty_dir):
    tables = ob.discover_tables(dirty_dir)
    all_data = {name: ob.read_csv(path) for name, path in tables.items()}
    roles = ob.resolve_roles(ob.profile_all_columns(all_data, verbose=False))

    result = ob.find_duplicates_v3(all_data, roles, llm_enabled=False)
    found = {
        tuple(sorted((str(d["id_a"]), str(d["id_b"]))))
        for d in result["confirmed_duplicates"]
    }

    with open(os.path.join(dirty_dir, "answer_key.json"), encoding="utf-8") as f:
        key = json.load(f)
    expected = {
        tuple(sorted((str(d["original_id"]), str(d["duplicate_id"]))))
        for d in key["duplicate_customers"]
    }

    assert found == expected, f"найдено {sorted(found)}, ожидалось {sorted(expected)}"


def test_non_numeric_ids_do_not_crash():
    """Раньше идентификаторы приводились к int() и падали на строковых ключах."""
    customers = [
        {"id": "CUST-A", "company_name": 'ООО "Альфа"', "city": "Москва", "email": "a@a.a"},
        {"id": "CUST-B", "company_name": '«Альфа» ООО', "city": "Москва", "email": "a@a.a"},
    ]
    roles = {"customers": {"pk": "id", "name": "company_name"}}
    pairs = ob.find_duplicate_candidates(customers, roles)
    assert len(pairs) == 1
    assert {pairs[0]["id_a"], pairs[0]["id_b"]} == {"CUST-A", "CUST-B"}
