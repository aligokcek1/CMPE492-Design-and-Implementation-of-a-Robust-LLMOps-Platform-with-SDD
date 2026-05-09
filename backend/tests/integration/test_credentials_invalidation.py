"""T057 — Background credential re-validation flips validation_status to `invalid`.

This is the integration test for FR-015 / T062a. It verifies:

1. A GCPAuthError raised during any background GCPProvider call made on behalf
   of a user flips the user's ``gcp_credentials.validation_status`` to
   ``invalid``.
2. After the flip, ``POST /api/deployments`` and ``DELETE /api/deployments/{id}``
   return 409 with ``{"code": "credentials_invalid"}``.
3. Already-running deployments are NOT torn down as a side effect.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select


async def _create_session(client: AsyncClient, username: str = "alice") -> str:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = username
        resp = await client.post("/api/auth/verify", json={"token": "hf_fake"})
    return resp.json()["session_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_valid_credentials(user_id: str = "alice") -> None:
    from src.db import get_session_factory
    from src.db.models import GCPCredentialsRow

    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(GCPCredentialsRow(
            user_id=user_id,
            service_account_json_encrypted=b"placeholder-never-decrypted-in-this-test",
            billing_account_id="billingAccounts/ABCDEF-012345-67890X",
            service_account_email="sa@example.iam.gserviceaccount.com",
            gcp_project_id_of_sa="sa-parent",
            last_validated_at=datetime.now(UTC),
            validation_status="valid",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()


def _seed_running_deployment(user_id: str = "alice") -> str:
    import uuid

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id=user_id,
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id="llmops-existing-running-01",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            endpoint_url="http://1.2.3.4:80",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()
    return dep_id


def _read_validation_status(user_id: str) -> str:
    from src.db import get_session_factory
    from src.db.models import GCPCredentialsRow

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
        ).scalar_one()
        return row.validation_status


@pytest.mark.asyncio
async def test_auth_failure_in_background_flips_credentials_to_invalid(
    temp_db, fake_gcp_provider, app_with_overrides,
):
    from src.services.gcp_fake_provider import GCPAuthError

    _seed_valid_credentials("alice")
    running_id = _seed_running_deployment("alice")

    # Program the fake to reject the next project_exists call with an auth error,
    # mirroring a revoked SA key.
    fake_gcp_provider.fail_on("project_exists", GCPAuthError("permission_denied"))

    from src.services.deployment_orchestrator import deployment_orchestrator

    await deployment_orchestrator.refresh_statuses(provider=fake_gcp_provider)

    assert _read_validation_status("alice") == "invalid"

    # The running deployment MUST still be running — no teardown side-effect.
    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            select(DeploymentRow).where(DeploymentRow.id == running_id)
        ).scalar_one()
    assert row.status == "running"


@pytest.mark.asyncio
async def test_post_and_delete_blocked_after_credentials_flipped_invalid(
    temp_db, fake_gcp_provider, app_with_overrides,
):
    from httpx import ASGITransport

    _seed_valid_credentials("alice")
    running_id = _seed_running_deployment("alice")

    from src.services.credentials_store import credentials_store

    await credentials_store.record_credentials_invalid(
        user_id="alice",
        error=RuntimeError("simulated revoked"),
    )

    transport = ASGITransport(app=app_with_overrides)

    # Skip the HF model gate for this test (we're asserting preflight, not routing).
    with patch("src.api.deployment.hf_models.is_supported_text_generation_model",
               new_callable=AsyncMock) as gate:
        gate.return_value = (True, "text-generation", "ok")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _create_session(client, username="alice")

            post_resp = await client.post(
                "/api/deployments",
                headers=_bearer(token),
                json={"hf_model_id": "Qwen/Qwen3-1.7B"},
            )
            delete_resp = await client.delete(
                f"/api/deployments/{running_id}",
                headers=_bearer(token),
            )

    assert post_resp.status_code == 409
    assert post_resp.json()["detail"]["code"] == "credentials_invalid"

    assert delete_resp.status_code == 409
    assert delete_resp.json()["detail"]["code"] == "credentials_invalid"
