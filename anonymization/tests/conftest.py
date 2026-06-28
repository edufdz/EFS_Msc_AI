import os
import sys

import pytest

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixture_path():
    def _get(name: str) -> str:
        return os.path.join(FIXTURES_DIR, name)
    return _get


@pytest.fixture
def load_fixture():
    def _load(name: str) -> str:
        path = os.path.join(FIXTURES_DIR, name)
        with open(path, encoding="utf-8") as f:
            return f.read()
    return _load
