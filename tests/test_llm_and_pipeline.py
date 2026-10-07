"""Разбор ответа модели, фолбэки и сквозной прогон без ключа API."""

import json
import os

import pytest

import ontology_builder_v3 as ob


def test_extract_json_plain():
    assert ob.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert ob.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ob.extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose_around():
    assert ob.extract_json('Вот ответ:\n{"a": 1}\nГотово.') == {"a": 1}


def test_extract_json_raises_on_garbage():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        ob.extract_json("нет тут никакого json")


def test_call_llm_disabled_returns_none():
    assert ob.call_llm("prompt", enabled=False) is None


def test_call_llm_without_key_returns_none(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert ob.call_llm("prompt", enabled=True) is None


def test_answer_key_absent_means_no_checks(tmp_path):
    key, path = ob.load_answer_key(str(tmp_path))
    assert path is None
    assert key == ob.EMPTY_ANSWER_KEY
    assert ob.validate({}, {}, {}, key) == []


def test_answer_key_broken_json_is_tolerated(tmp_path):
    (tmp_path / ob.ANSWER_KEY_NAME).write_text("{не json", encoding="utf-8")
    key, path = ob.load_answer_key(str(tmp_path))
    assert path is None and key == ob.EMPTY_ANSWER_KEY


def test_discover_tables_orders_known_first(tmp_path):
    for name in ("zzz.csv", "orders.csv", "customers.csv"):
        (tmp_path / name).write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("не csv", encoding="utf-8")
    tables = ob.discover_tables(str(tmp_path))
    assert list(tables) == ["customers", "orders", "zzz"]


def test_end_to_end_without_llm_passes_answer_key(dirty_dir, monkeypatch):
    """Главная регрессия: раньше пайплайн падал на этапе 4 с KeyError: 'id'."""
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    args = ob.parse_args([
        "--data-dir", dirty_dir,
        "--no-llm",
        "--output", os.path.join(dirty_dir, "graph_test.json"),
    ])
    result = ob.run(args)

    assert result["checks"], "этап сверки не выполнился"
    failed = [c for c in result["checks"] if not c["passed"]]
    assert not failed, f"провалены проверки: {failed}"
    assert result["graph"]["entities"], "граф сущностей пуст"
    assert result["graph"]["relationships"], "связи не найдены"

    with open(os.path.join(dirty_dir, "graph_test.json"), encoding="utf-8") as f:
        saved = json.load(f)
    assert "entity_graph" in saved and "duplicate_analysis" in saved


def test_end_to_end_clean_data_runs(clean_dir, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    args = ob.parse_args([
        "--data-dir", clean_dir, "--no-llm", "--no-write",
        "--stock-threshold", "50",
        "--output", os.path.join(clean_dir, "graph_test.json"),
    ])
    result = ob.run(args)
    assert result["low_stock"], "при пороге 50 должны найтись позиции"
    assert result["checks"] == [], "без answer_key.json проверок быть не должно"
