from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.models.deployment import MockDeploymentResponse


async def _session_auth_headers(client: AsyncClient) -> dict[str, str]:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_mock_deploy_cpu_success(transport):
    mock_response = MockDeploymentResponse(
        status="mock_success",
        message="Mock deployment of 'user/model' on CPU completed successfully.",
    )
    with patch("src.api.deployment.mock_deploy", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = mock_response
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/deployment/mock",
                json={"model_repository": "user/model", "resource_type": "CPU"},
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "mock_success"
    assert "message" in data


@pytest.mark.asyncio
async def test_mock_deploy_gpu_success(transport):
    mock_response = MockDeploymentResponse(
        status="mock_success",
        message="Mock deployment of 'user/model' on GPU completed successfully.",
    )
    with patch("src.api.deployment.mock_deploy", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = mock_response
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/deployment/mock",
                json={"model_repository": "user/model", "resource_type": "GPU"},
                headers=headers,
            )
    assert response.status_code == 200
    assert response.json()["status"] == "mock_success"


@pytest.mark.asyncio
async def test_mock_deploy_missing_token(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/deployment/mock",
            json={"model_repository": "user/model", "resource_type": "CPU"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mock_deploy_invalid_resource_type(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        response = await client.post(
            "/api/deployment/mock",
            json={"model_repository": "user/model", "resource_type": "TPU"},
            headers=headers,
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mock_deploy_idempotency_replay(transport):
    mock_response = MockDeploymentResponse(
        status="mock_success",
        message="Mock deployment of 'user/model' on CPU completed successfully.",
    )
    with patch("src.api.deployment.mock_deploy", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = mock_response
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            headers["X-Idempotency-Key"] = "retry-deploy-1"
            first = await client.post(
                "/api/deployment/mock",
                json={"model_repository": "user/model", "resource_type": "CPU"},
                headers=headers,
            )
            second = await client.post(
                "/api/deployment/mock",
                json={"model_repository": "user/model", "resource_type": "CPU"},
                headers=headers,
            )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert mock_fn.call_count == 1


# =========================================================================== #
# US2 — Real public-model deployment contract tests                            #
# =========================================================================== #

import json  # noqa: E402
import uuid  # noqa: E402

_VALID_SA_JSON = json.dumps({
    "type": "service_account",
    "project_id": "sa-parent-project",
    "private_key_id": "abc",
    "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
    "client_email": "sa@sa-parent-project.iam.gserviceaccount.com",
})
_VALID_BILLING = "billingAccounts/ABCDEF-012345-67890X"


async def _ensure_credentials(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/gcp/credentials",
        headers=headers,
        json={
            "service_account_json": _VALID_SA_JSON,
            "billing_account_id": _VALID_BILLING,
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
def supported_hf_model(monkeypatch):
    """Stub out the HF metadata gate so tests never hit huggingface.co."""

    async def _is_supported(model_id: str) -> tuple[bool, str, str]:
        if "unsupported" in model_id.lower():
            return False, "image-classification", "model pipeline is image-classification, not text generation"
        return True, "text-generation", "ok"

    from src.services import hf_models

    monkeypatch.setattr(hf_models, "is_supported_text_generation_model", _is_supported)
    return _is_supported


# --------------------------------------------------------------------------- #
# T028 — POST /api/deployments                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_create_deployment_success_202(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["id"]
    assert body["hf_model_id"] == "Qwen/Qwen3-1.7B"
    assert body["status"] in ("queued", "deploying")


@pytest.mark.asyncio
async def test_create_deployment_unsupported_model_returns_400(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "someone/unsupported-image-model"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_model"


@pytest.mark.asyncio
async def test_create_deployment_requires_credentials_409(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        # Deliberately skip _ensure_credentials

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "credentials_missing"


@pytest.mark.asyncio
async def test_create_deployment_rejects_when_credentials_invalid_409(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        # Flip stored credentials to invalid (simulating what T062a will do in US4)
        from src.services.credentials_store import credentials_store

        await credentials_store.record_credentials_invalid(
            user_id="test_user",
            error=RuntimeError("simulated permission revoked"),
        )

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "credentials_invalid"


@pytest.mark.asyncio
async def test_create_deployment_cap_reached_returns_409(transport, supported_hf_model):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        # Seed 3 active deployments for the user
        session_factory = get_session_factory()
        with session_factory() as db:
            for idx in range(3):
                db.add(DeploymentRow(
                    id=str(uuid.uuid4()),
                    user_id="test_user",
                    hf_model_id=f"some/model-{idx}",
                    hf_model_display_name=f"Model {idx}",
                    gcp_project_id=f"llmops-existing{idx}-aaaa{idx}",
                    gke_cluster_name="llmops-cluster",
                    gke_region="us-central1",
                    status="running",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ))
            db.commit()

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "concurrent_deployment_limit"


@pytest.mark.asyncio
async def test_create_deployment_duplicate_model_requires_confirmation(transport, supported_hf_model):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(DeploymentRow(
                id=str(uuid.uuid4()),
                user_id="test_user",
                hf_model_id="Qwen/Qwen3-1.7B",
                hf_model_display_name="Qwen3 1.7B",
                gcp_project_id="llmops-existing-dup01",
                gke_cluster_name="llmops-cluster",
                gke_region="us-central1",
                status="running",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ))
            db.commit()

        first = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )
        second = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "force": True},
        )

    assert first.status_code == 409
    body = first.json()["detail"]
    assert body["code"] == "duplicate_model_requires_confirmation"
    assert body.get("require_confirmation") is True

    assert second.status_code == 202


@pytest.mark.asyncio
async def test_create_deployment_requires_session_401(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/deployments", json={"hf_model_id": "Qwen/Qwen3-1.7B"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# T029 — GET /api/deployments/{id}                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_get_deployment_returns_detail_with_gcp_fields(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        create_resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )
        assert create_resp.status_code == 202
        dep_id = create_resp.json()["id"]

        detail_resp = await client.get(f"/api/deployments/{dep_id}", headers=headers)

    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["id"] == dep_id
    assert body["gcp_project_id"].startswith("llmops-")
    assert body["gke_cluster_name"] == "llmops-cluster"
    assert body["gke_region"] == "us-central1"
    assert body["gcp_console_url"].startswith("https://console.cloud.google.com/")


@pytest.mark.asyncio
async def test_get_deployment_not_owner_returns_404(transport, supported_hf_model):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    foreign_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=foreign_id,
            user_id="someone_else",
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id="llmops-foreign-aaaa01",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{foreign_id}", headers=headers)

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# T045 / T046 — GET /api/deployments                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_list_deployments_returns_only_callers_rows(transport, supported_hf_model):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    # Seed: 1 row for caller, 1 row for somebody else
    mine_id = str(uuid.uuid4())
    theirs_id = str(uuid.uuid4())

    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=mine_id,
            user_id="test_user",
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id="llmops-mine-aaaa01",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            endpoint_url="http://1.2.3.4:80",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.add(DeploymentRow(
            id=theirs_id,
            user_id="someone_else",
            hf_model_id="Qwen/Qwen3-4B",
            hf_model_display_name="Qwen3 4B",
            gcp_project_id="llmops-theirs-bbbb02",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get("/api/deployments", headers=headers)

    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert mine_id in ids
    assert theirs_id not in ids


@pytest.mark.asyncio
async def test_list_deployments_empty_state(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get("/api/deployments", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_deployments_requires_session_401(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/deployments")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# T054 — DELETE /api/deployments/{id}                                          #
# --------------------------------------------------------------------------- #

def _seed_row(user_id: str, status: str = "running", deployment_id: str | None = None) -> str:
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = deployment_id or str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id=user_id,
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status=status,
            endpoint_url="http://1.2.3.4:80" if status == "running" else None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()
    return dep_id


@pytest.mark.asyncio
async def test_delete_deployment_returns_202_and_status_deleting(transport, fake_gcp_provider):
    # Pre-register the project in the fake so delete doesn't 404
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        dep_id = _seed_row("test_user", status="running")
        # Seed project in the fake provider so delete_project finds it
        fake_gcp_provider.seed_project(
            project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
        )
        # Make delete_project block briefly so we can observe the transient "deleting" status
        fake_gcp_provider.artificial_latency_seconds = 0.1

        resp = await client.delete(f"/api/deployments/{dep_id}", headers=headers)

    assert resp.status_code == 202
    assert resp.json()["status"] in ("deleting", "deleted")


@pytest.mark.asyncio
async def test_delete_deployment_not_owner_returns_404(transport):
    foreign_id = _seed_row("someone_else", status="running")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.delete(f"/api/deployments/{foreign_id}", headers=headers)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_deployment_requires_session_401(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/deployments/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_deployment_blocked_when_credentials_invalid_409(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        dep_id = _seed_row("test_user", status="running")

        from src.services.credentials_store import credentials_store

        await credentials_store.record_credentials_invalid(
            user_id="test_user",
            error=RuntimeError("simulated revoke"),
        )

        resp = await client.delete(f"/api/deployments/{dep_id}", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "credentials_invalid"


# --------------------------------------------------------------------------- #
# T055 — POST /api/deployments/{id}/dismiss                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_dismiss_lost_deployment_returns_204(transport):
    dep_id = _seed_row("test_user", status="lost")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(f"/api/deployments/{dep_id}/dismiss", headers=headers)

    assert resp.status_code == 204

    # Row should be hard-deleted (GET returns 404)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        after = await client.get(f"/api/deployments/{dep_id}", headers=headers)
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_dismiss_non_lost_deployment_returns_409(transport):
    dep_id = _seed_row("test_user", status="running")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(f"/api/deployments/{dep_id}/dismiss", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_lost"


@pytest.mark.asyncio
async def test_dismiss_not_owner_returns_404(transport):
    foreign_id = _seed_row("someone_else", status="lost")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(f"/api/deployments/{foreign_id}/dismiss", headers=headers)

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# T067 — POST /api/deployments/{id}/inference                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_inference_happy_path_200(transport):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id="test_user",
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            endpoint_url="http://192.0.2.42:80",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()

    canned_response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{
            "message": {"role": "assistant", "content": "Hello!"},
            "index": 0,
            "finish_reason": "stop",
        }],
    }

    with patch("src.services.inference_proxy.forward", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = canned_response
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            resp = await client.post(
                f"/api/deployments/{dep_id}/inference",
                headers=headers,
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hello!"


@pytest.mark.asyncio
async def test_inference_when_not_running_returns_409(transport):
    dep_id = _seed_row("test_user", status="deploying")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(
            f"/api/deployments/{dep_id}/inference",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_running"


@pytest.mark.asyncio
async def test_inference_upstream_timeout_returns_504(transport):
    from datetime import UTC, datetime

    import httpx

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id="test_user",
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            endpoint_url="http://192.0.2.42:80",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()

    with patch("src.services.inference_proxy.forward", new_callable=AsyncMock) as mock_forward:
        mock_forward.side_effect = httpx.ReadTimeout("simulated 120s")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            resp = await client.post(
                f"/api/deployments/{dep_id}/inference",
                headers=headers,
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

    assert resp.status_code == 504
    assert resp.json()["detail"]["code"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_inference_not_owner_returns_404(transport):
    foreign_id = _seed_row("someone_else", status="running")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(
            f"/api/deployments/{foreign_id}/inference",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert resp.status_code == 404
