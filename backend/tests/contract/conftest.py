from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport

_GENERATED_KEY = Fernet.generate_key().decode()
os.environ.setdefault("LLMOPS_ENCRYPTION_KEY", _GENERATED_KEY)
os.environ.setdefault("LLMOPS_USE_FAKE_GCP", "1")
os.environ.setdefault("LLMOPS_METRICS_DISABLED", "1")
os.environ.setdefault("LLMOPS_USE_FAKE_METRICS_QUERY", "1")
os.environ.setdefault("LLMOPS_GRAFANA_SIGNING_SECRET", "test-signing-secret-for-contract-tests")
os.environ.setdefault("LLMOPS_DISABLE_STATUS_REFRESH", "1")


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
def fake_lightning_ai_provider():
    from src.services.lightning_ai_fake_provider import FakeLightningAIProvider

    return FakeLightningAIProvider()


@pytest.fixture
def fake_prometheus_provisioner():
    from src.services.prometheus_fake_provisioner import FakePrometheusProvisioner

    return FakePrometheusProvisioner()


@pytest.fixture
def fake_grafana_provisioner():
    from src.services.grafana_fake_provisioner import FakeGrafanaProvisioner

    return FakeGrafanaProvisioner()


@pytest.fixture
def fake_metrics_query_client():
    from src.services.metrics_query import FakeMetricsQueryClient

    return FakeMetricsQueryClient()


@pytest.fixture
def app_with_overrides(
    temp_db,
    fake_gcp_provider,
    fake_lightning_ai_provider,
    fake_metrics_query_client,
):
    """Yields the FastAPI app with cloud + metrics dependencies swapped for fakes."""
    from src.api.dependencies import get_metrics_query_service
    from src.main import (
        app,
        get_gcp_provider,
        get_lightning_ai_provider,
        reset_gcp_provider_for_tests,
        reset_lightning_ai_provider_for_tests,
    )
    from src.services.metrics_query import MetricsQueryService

    reset_gcp_provider_for_tests()
    reset_lightning_ai_provider_for_tests()
    app.dependency_overrides[get_gcp_provider] = lambda: fake_gcp_provider
    app.dependency_overrides[get_lightning_ai_provider] = lambda: fake_lightning_ai_provider
    app.dependency_overrides[get_metrics_query_service] = lambda: MetricsQueryService(
        client=fake_metrics_query_client
    )
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_gcp_provider, None)
        app.dependency_overrides.pop(get_lightning_ai_provider, None)
        app.dependency_overrides.pop(get_metrics_query_service, None)
        reset_gcp_provider_for_tests()
        reset_lightning_ai_provider_for_tests()


@pytest.fixture
def transport(app_with_overrides) -> ASGITransport:
    return ASGITransport(app=app_with_overrides)


@pytest.fixture(autouse=True)
def reset_session_store() -> None:
    from src.services.session_store import session_store

    session_store._sessions.clear()  # noqa: SLF001 - test-only cleanup
    session_store._idempotency.clear()  # noqa: SLF001 - test-only cleanup
