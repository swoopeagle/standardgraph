"""Shared fixtures for StandardGraph tests."""
import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(__file__).parent.parent / "data" / "common_core.db"


@pytest.fixture(scope="session")
def db():
    """Read-only DB connection shared across the test session."""
    assert DB_PATH.exists(), f"DB not found: {DB_PATH}"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
