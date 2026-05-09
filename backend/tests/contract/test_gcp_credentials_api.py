from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def _valid_sa_json(email: str = "sa@proj.iam.gserviceaccount.com", project_id: str = "my-sa-project") -> str:
    return json.dumps({
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": "abc123",
        "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
        "client_email": email,
        "client_id": "123",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    })


_VALID_BILLING = "billingAccounts/ABCDEF-012345-67890X"


async def _create_session(client: AsyncClient, username: str = "alice") -> str:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = username
        resp = await client.post("/api/auth/verify", json={"token": "hf_token"})
    assert resp.status_code == 200
    return resp.json()["session_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# T015 — POST /api/gcp/credentials                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_post_credentials_saves_and_returns_status_200(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)

        response = await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["service_account_email"] == "sa@proj.iam.gserviceaccount.com"
    assert body["gcp_project_id_of_sa"] == "my-sa-project"
    assert body["billing_account_id"] == _VALID_BILLING
    assert body["validation_status"] == "valid"
    assert body["last_validated_at"] is not None
    assert "service_account_json" not in body


@pytest.mark.asyncio
async def test_post_credentials_rejects_malformed_json_400(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)

        response = await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": "not-json-at-all",
                "billing_account_id": _VALID_BILLING,
            },
        )

    assert response.status_code == 400
    detail = response.json()
    # FastAPI wraps custom HTTPException detail under {"detail": ...}
    assert detail["detail"]["code"]  # some structured error code present


@pytest.mark.asyncio
async def test_post_credentials_validation_failure_does_not_save(transport, fake_gcp_provider):
    from src.services.gcp_fake_provider import GCPAuthError

    fake_gcp_provider.fail_on("validate_credentials", GCPAuthError("permission denied"))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)

        post_resp = await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )
        assert post_resp.status_code == 400

        get_resp = await client.get("/api/gcp/credentials", headers=_bearer(token))

    assert get_resp.status_code == 200
    assert get_resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_post_credentials_requires_session_401(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/gcp/credentials",
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# T016 — GET /api/gcp/credentials                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_get_credentials_initial_is_unconfigured(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)
        resp = await client.get("/api/gcp/credentials", headers=_bearer(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    # Do NOT leak any of the secret-adjacent fields when not configured
    assert body.get("service_account_email") is None
    assert body.get("billing_account_id") is None


@pytest.mark.asyncio
async def test_get_credentials_never_returns_secret_material(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)
        await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )
        resp = await client.get("/api/gcp/credentials", headers=_bearer(token))

    raw = resp.text
    assert "private_key" not in raw
    assert "BEGIN PRIVATE KEY" not in raw
    assert "service_account_json" not in raw


@pytest.mark.asyncio
async def test_get_credentials_requires_session_401(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/gcp/credentials")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# T017 — DELETE /api/gcp/credentials                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_delete_credentials_success_204(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)
        await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )

        delete_resp = await client.delete("/api/gcp/credentials", headers=_bearer(token))
        get_resp = await client.get("/api/gcp/credentials", headers=_bearer(token))

    assert delete_resp.status_code == 204
    assert get_resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_delete_credentials_blocked_when_active_deployment_exists_409(transport):
    """FR-007 says deployments require credentials to be torn down first. The
    *inverse* — credentials can't be deleted while deployments are still
    owed teardown — is enforced here and required by the OpenAPI 409 contract.
    """
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _create_session(client)
        await client.post(
            "/api/gcp/credentials",
            headers=_bearer(token),
            json={
                "service_account_json": _valid_sa_json(),
                "billing_account_id": _VALID_BILLING,
            },
        )

        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(DeploymentRow(
                id=str(uuid.uuid4()),
                user_id="alice",
                hf_model_id="Qwen/Qwen3-1.7B",
                hf_model_display_name="Qwen3 1.7B",
                gcp_project_id=f"llmops-{uuid.uuid4().hex[:8]}-test01",
                gke_cluster_name="llmops-cluster",
                gke_region="us-central1",
                status="running",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ))
            db.commit()

        resp = await client.delete("/api/gcp/credentials", headers=_bearer(token))

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "active_deployments_exist"


@pytest.mark.asyncio
async def test_delete_credentials_requires_session_401(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/gcp/credentials")
    assert resp.status_code == 401
