from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport


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


@pytest.fixture
def app_with_overrides(temp_db, fake_gcp_provider):
    """Yields the FastAPI app with GCPProvider swapped for the in-memory fake."""
    from src.main import app, get_gcp_provider, reset_gcp_provider_for_tests

    reset_gcp_provider_for_tests()
    app.dependency_overrides[get_gcp_provider] = lambda: fake_gcp_provider
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_gcp_provider, None)
        reset_gcp_provider_for_tests()


@pytest.fixture
def transport(app_with_overrides) -> ASGITransport:
    return ASGITransport(app=app_with_overrides)


@pytest.fixture(autouse=True)
def reset_session_store() -> None:
    from src.services.session_store import session_store

    session_store._sessions.clear()  # noqa: SLF001 - test-only cleanup
    session_store._idempotency.clear()  # noqa: SLF001 - test-only cleanup
