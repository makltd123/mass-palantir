"""Общие фикстуры: генерируем данные в tmp, чтобы не трогать файлы репозитория."""

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def _generate(script, out_dir):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, script), "--out-dir", str(out_dir)],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        pytest.fail(f"{script} упал:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return str(out_dir)


@pytest.fixture(scope="session")
def dirty_dir(tmp_path_factory):
    """«Грязные» данные + answer_key.json."""
    return _generate("generate_dirty_data.py", tmp_path_factory.mktemp("dirty"))


@pytest.fixture(scope="session")
def clean_dir(tmp_path_factory):
    """Чистые данные (без ключа ответов)."""
    return _generate("generate_realistic_data.py", tmp_path_factory.mktemp("clean"))
