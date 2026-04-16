from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


_GENERATED_KEY = Fernet.generate_key().decode()
os.environ.setdefault("LLMOPS_ENCRYPTION_KEY", _GENERATED_KEY)
os.environ.setdefault("LLMOPS_USE_FAKE_GCP", "1")


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


@pytest.fixture
def fake_gcp_provider():
    from src.services.gcp_fake_provider import FakeGCPProvider

    return FakeGCPProvider()
