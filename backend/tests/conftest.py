from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "llmops-test.db"
    os.environ["LLMOPS_DATABASE_URL"] = f"sqlite:///{db_file}"

    from src import db as db_pkg

    db_pkg.reset_engine_for_tests()

    from src.db.migrations import ensure_schema

    ensure_schema()
    yield db_file

    db_pkg.reset_engine_for_tests()
    os.environ.pop("LLMOPS_DATABASE_URL", None)
