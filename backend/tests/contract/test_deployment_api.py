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

    async def _is_supported(
        model_id: str,
        *,
        hf_token: str | None = None,
        timeout: int = 10,
    ) -> tuple[bool, str, str]:
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["id"]
    assert body["hf_model_id"] == "Qwen/Qwen3-1.7B"
    assert body["hardware_type"] == "cpu"
    assert body["status"] in ("queued", "deploying")


@pytest.mark.asyncio
async def test_create_deployment_unsupported_model_returns_400(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "someone/unsupported-image-model", "hardware_type": "cpu"},
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
        )
        second = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu", "force": True},
        )

    assert first.status_code == 409
    body = first.json()["detail"]
    assert body["code"] == "duplicate_model_requires_confirmation"
    assert body.get("require_confirmation") is True

    assert second.status_code == 202


@pytest.mark.asyncio
async def test_create_deployment_requires_session_401(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/deployments", json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"})
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
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
        )
        assert create_resp.status_code == 202
        dep_id = create_resp.json()["id"]

        detail_resp = await client.get(f"/api/deployments/{dep_id}", headers=headers)

    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["id"] == dep_id
    assert body["hardware_type"] == "cpu"
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

def _seed_row(
    user_id: str,
    status: str = "running",
    deployment_id: str | None = None,
    hardware_type: str = "cpu",
) -> str:
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = deployment_id or str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        if hardware_type == "cpu":
            db.add(DeploymentRow(
                id=dep_id,
                user_id=user_id,
                hf_model_id="Qwen/Qwen3-1.7B",
                hf_model_display_name="Qwen3 1.7B",
                hardware_type="cpu",
                gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
                gke_cluster_name="llmops-cluster",
                gke_region="us-central1",
                status=status,
                endpoint_url="http://1.2.3.4:80" if status == "running" else None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ))
        else:
            db.add(DeploymentRow(
                id=dep_id,
                user_id=user_id,
                hf_model_id="Qwen/Qwen3-1.7B",
                hf_model_display_name="Qwen3 1.7B",
                hardware_type="gpu",
                lightning_ai_deployment_id=f"lai-{dep_id[:8]}",
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
async def test_inference_records_prometheus_metrics(transport, monkeypatch):
    """Feature 010: successful inference increments proxy-emitted metrics."""
    monkeypatch.setenv("LLMOPS_METRICS_DISABLED", "0")
    dep_id = _seed_row("test_user", status="running")

    with patch("src.services.metrics_recorder.record_success") as mock_record:
        with patch("src.services.inference_proxy._forward_tgi", new_callable=AsyncMock) as mock_tgi:
            from src.services.inference_proxy import _to_openai_chat_response

            mock_tgi.return_value = _to_openai_chat_response("Hello world from metrics test")
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _session_auth_headers(client)
                resp = await client.post(
                    f"/api/deployments/{dep_id}/inference",
                    headers=headers,
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )

    assert resp.status_code == 200
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["deployment_id"] == dep_id
    assert mock_record.call_args.kwargs["user_id"] == "test_user"
    assert mock_record.call_args.kwargs["token_count"] >= 1


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


# =========================================================================== #
# T007 — hardware_type field validation on POST /api/deployments               #
# =========================================================================== #

@pytest.mark.asyncio
async def test_create_deployment_without_hardware_type_returns_422(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_deployment_invalid_hardware_type_returns_422(transport, supported_hf_model):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)
        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "tpu"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_deployments_includes_hardware_type_field(transport, supported_hf_model):
    """GET /api/deployments returns hardware_type on every record (T007c)."""
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
            hardware_type="cpu",
            gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
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
    items = resp.json()
    assert len(items) >= 1
    for item in items:
        assert "hardware_type" in item
    assert any(item["id"] == dep_id and item["hardware_type"] == "cpu" for item in items)


# =========================================================================== #
# T016 — GPU deployment contract tests                                          #
# =========================================================================== #

@pytest.mark.asyncio
async def test_gpu_deploy_missing_lightning_key_returns_409(transport, supported_hf_model):
    """GPU deploy without a Lightning AI key → 409 lightning_credentials_missing."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "gpu"},
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "lightning_credentials_missing"


@pytest.mark.asyncio
async def test_gpu_deploy_invalid_lightning_key_returns_409(transport, supported_hf_model, fake_lightning_ai_provider):
    """GPU deploy with an invalid Lightning AI key → 409 lightning_credentials_invalid."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        # Save a valid key first, then flip it to invalid
        await client.post(
            "/api/lightning/credentials",
            headers=headers,
            json={"lightning_user_id": "fake-lai-uid-123", "api_key": "lai-validkey"},
        )
        from src.services.lightning_ai_credentials_store import lightning_ai_credentials_store
        await lightning_ai_credentials_store.record_key_invalid(
            user_id="test_user",
            error=RuntimeError("simulated revoke"),
        )
        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "gpu"},
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "lightning_credentials_invalid"


@pytest.mark.asyncio
async def test_gpu_deploy_happy_path_202(transport, supported_hf_model, fake_lightning_ai_provider):
    """GPU deploy with valid key returns 202 with hardware_type=gpu."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await client.post(
            "/api/lightning/credentials",
            headers=headers,
            json={"lightning_user_id": "fake-lai-uid-123", "api_key": "lai-validkey"},
        )
        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "gpu"},
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["hardware_type"] == "gpu"
    assert body["status"] in ("queued", "deploying")


@pytest.mark.asyncio
async def test_gpu_delete_transitions_to_deleted(transport, fake_lightning_ai_provider):
    """DELETE on a GPU deployment calls Lightning AI SDK and marks record deleted."""
    dep_id = _seed_row("test_user", status="running", hardware_type="gpu")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        # Ensure Lightning AI key is present for delete credential check
        await client.post(
            "/api/lightning/credentials",
            headers=headers,
            json={"lightning_user_id": "fake-lai-uid-123", "api_key": "lai-validkey"},
        )
        resp = await client.delete(f"/api/deployments/{dep_id}", headers=headers)

    assert resp.status_code == 202
    assert resp.json()["status"] in ("deleting", "deleted")


@pytest.mark.asyncio
async def test_gpu_inference_proxy_uses_endpoint_url(transport):
    """Inference proxy works for GPU deployment (uses stored endpoint_url, hardware-agnostic)."""
    dep_id = _seed_row("test_user", status="running", hardware_type="gpu")

    canned = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    with patch("src.services.inference_proxy.forward", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = canned
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            resp = await client.post(
                f"/api/deployments/{dep_id}/inference",
                headers=headers,
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
    assert resp.status_code == 200


# =========================================================================== #
# 009 — model_origin, HF_TOKEN injection, new error codes (T007–T011, T034–T038) #
# =========================================================================== #

@pytest.fixture
def supported_hf_model_authenticated(monkeypatch):
    """Like supported_hf_model but accepts the new hf_token and timeout params."""

    async def _is_supported(
        model_id: str,
        *,
        hf_token: str | None = None,
        timeout: int = 10,
    ) -> tuple[bool, str, str]:
        if "unsupported" in model_id.lower():
            return False, "image-classification", "unsupported pipeline"
        if "unreachable" in model_id.lower():
            return False, "unreachable", "HuggingFace Hub is currently unreachable, please retry."
        if "denied" in model_id.lower():
            return False, "access_denied", "Token lacks read access to this repository."
        return True, "text-generation", "ok"

    from src.services import hf_models

    monkeypatch.setattr(hf_models, "is_supported_text_generation_model", _is_supported)
    return _is_supported


async def _ensure_lightning_credentials(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/lightning/credentials",
        headers=headers,
        json={"lightning_user_id": "fake-lai-uid-009", "api_key": "lai-key-009"},
    )
    assert resp.status_code == 200, resp.text


# T007 — user-owned model sets model_origin = "uploaded"
@pytest.mark.asyncio
async def test_deploy_user_owned_model_sets_model_origin_uploaded(
    transport, supported_hf_model_authenticated
):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "test_user/private-model", "hardware_type": "cpu"},
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["model_origin"] == "uploaded"


# T008 — third-party model sets model_origin = "public"
@pytest.mark.asyncio
async def test_deploy_third_party_model_sets_model_origin_public(
    transport, supported_hf_model_authenticated
):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "org/some-model", "hardware_type": "cpu"},
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["model_origin"] == "public"


# T009 — HF Hub unreachable returns 400 hf_hub_unreachable
@pytest.mark.asyncio
async def test_deploy_hf_hub_unreachable_returns_400(
    transport, supported_hf_model_authenticated
):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "org/unreachable-model", "hardware_type": "cpu"},
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "hf_hub_unreachable"
    assert "unreachable" in detail["message"].lower()
    assert "retry" in detail["message"].lower()


# T010 — token lacks access returns 400 model_access_denied
@pytest.mark.asyncio
async def test_deploy_model_access_denied_returns_400(
    transport, supported_hf_model_authenticated
):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "org/access-denied-model", "hardware_type": "cpu"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "model_access_denied"


# T011 — GET /api/deployments list items include model_origin
@pytest.mark.asyncio
async def test_list_deployments_each_item_has_model_origin(transport):
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id="test_user",
            hf_model_id="test_user/my-model",
            hf_model_display_name="My Model",
            hardware_type="cpu",
            model_origin="uploaded",
            gcp_project_id=f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
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
    items = resp.json()
    assert all("model_origin" in item for item in items)
    uploaded = next((i for i in items if i["id"] == dep_id), None)
    assert uploaded is not None
    assert uploaded["model_origin"] == "uploaded"


# T009b — user-uploaded model with no pipeline_tag bypasses the unsupported check
@pytest.mark.asyncio
async def test_deploy_user_owned_model_with_unknown_pipeline_tag_allowed(transport):
    """If a user-uploaded model has pipeline_tag=unknown, deployment is allowed (bypass)."""
    from unittest.mock import patch as _patch

    from src.services import hf_models as _hf

    async def _unknown_gate(model_id, *, hf_token=None, timeout=10):
        return False, "unknown", "Model pipeline tag is 'unknown'"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        with _patch.object(_hf, "is_supported_text_generation_model", _unknown_gate), \
             _patch.object(_hf, "get_display_name", return_value="My Model"):
            resp = await client.post(
                "/api/deployments",
                headers=headers,
                json={"hf_model_id": "test_user/no-tag-model", "hardware_type": "cpu"},
            )

    assert resp.status_code == 202, resp.text
    assert resp.json()["model_origin"] == "uploaded"


@pytest.mark.asyncio
async def test_deploy_third_party_model_with_unknown_pipeline_tag_rejected(transport):
    """A third-party model with pipeline_tag=unknown is still rejected (bypass only for owned)."""
    from unittest.mock import patch as _patch

    from src.services import hf_models as _hf

    async def _unknown_gate(model_id, *, hf_token=None, timeout=10):
        return False, "unknown", "Model pipeline tag is 'unknown'"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        with _patch.object(_hf, "is_supported_text_generation_model", _unknown_gate):
            resp = await client.post(
                "/api/deployments",
                headers=headers,
                json={"hf_model_id": "some-org/their-model", "hardware_type": "cpu"},
            )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_model"


# T034 — GET /api/deployments/{id} includes model_origin
@pytest.mark.asyncio
async def test_get_deployment_by_id_includes_model_origin(
    transport, supported_hf_model_authenticated
):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        create_resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "test_user/my-private", "hardware_type": "cpu"},
        )
        assert create_resp.status_code == 202
        dep_id = create_resp.json()["id"]

        detail_resp = await client.get(f"/api/deployments/{dep_id}", headers=headers)

    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert "model_origin" in body
    assert body["model_origin"] == "uploaded"


# T035 — HF token must not appear in deployment API response (SC-005 / Constitution II)
@pytest.mark.asyncio
async def test_deployment_response_does_not_contain_hf_token(
    transport, supported_hf_model_authenticated
):
    """The session token 'hf_valid_token' must never appear in any response field."""
    hf_token_value = "hf_valid_token"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "test_user/private-model", "hardware_type": "cpu"},
        )

    assert resp.status_code == 202
    response_text = resp.text
    assert hf_token_value not in response_text, (
        f"HF token '{hf_token_value}' must not appear in deployment response body"
    )

    from sqlalchemy import inspect as sa_inspect

    from src.db import get_engine

    inspector = sa_inspect(get_engine())
    col_names = {col["name"] for col in inspector.get_columns("deployments")}
    assert "hf_token" not in col_names, "DeploymentRow must not have an hf_token column"


# T036 — GPU deploy for public model still passes hf_token to provider (FR-002 universal injection)
@pytest.mark.asyncio
async def test_gpu_deploy_public_model_injects_hf_token_to_provider(
    transport, supported_hf_model_authenticated, fake_lightning_ai_provider
):
    """Even for model_origin='public' GPU deploys, hf_token must reach the provider."""
    received_tokens: list[str] = []

    original_deploy = fake_lightning_ai_provider.deploy

    async def _spy_deploy(*, hf_model_id: str, api_key: str, lightning_user_id: str = "", hf_token: str = "") -> tuple[str, str | None]:
        received_tokens.append(hf_token)
        return await original_deploy(
            hf_model_id=hf_model_id,
            api_key=api_key,
            lightning_user_id=lightning_user_id,
            hf_token=hf_token,
        )

    fake_lightning_ai_provider.deploy = _spy_deploy

    import asyncio as _asyncio

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_lightning_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "org/public-model", "hardware_type": "gpu"},
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["model_origin"] == "public"

    await _asyncio.sleep(0.1)

    assert len(received_tokens) == 1, "provider.deploy() should have been called once"
    assert received_tokens[0] != "", "hf_token must be non-empty for GPU deploy"


# T037 — pre-deploy check timeout surfaces correct error code (SC-006)
@pytest.mark.asyncio
async def test_deploy_hf_hub_slow_times_out_with_hf_hub_unreachable(transport):
    """When is_supported_text_generation_model returns 'unreachable', API returns 400 hf_hub_unreachable."""
    import asyncio

    async def _slow_gate(model_id: str, *, hf_token: str | None = None, timeout: int = 10) -> tuple[bool, str, str]:
        await asyncio.sleep(0)  # yield; real impl uses HfApi(timeout=timeout)
        return False, "unreachable", "HuggingFace Hub is currently unreachable, please retry."

    from unittest.mock import patch as _patch

    from src.services import hf_models

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)

        with _patch.object(hf_models, "is_supported_text_generation_model", _slow_gate):
            resp = await client.post(
                "/api/deployments",
                headers=headers,
                json={"hf_model_id": "org/any-model", "hardware_type": "cpu"},
            )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "hf_hub_unreachable"
    assert detail["message"] == "HuggingFace Hub is currently unreachable, please retry."


# T038 — runtime token-revoked error during deploy produces human-readable status_message (FR-007)
@pytest.mark.asyncio
async def test_deployment_status_message_human_readable_on_token_revoked(
    transport, supported_hf_model_authenticated, fake_lightning_ai_provider
):
    """When Lightning AI auth fails during deploy (token revoked), status_message must be human-readable."""
    from src.services.lightning_ai_provider import LightningAIAuthError

    fake_lightning_ai_provider.deploy_raises = LightningAIAuthError

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_lightning_credentials(client, headers)

        resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "test_user/private-model", "hardware_type": "gpu"},
        )

    assert resp.status_code == 202

    import asyncio
    await asyncio.sleep(0.1)

    from src.services.deployment_store import deployment_store

    dep_id = resp.json()["id"]
    row = deployment_store.get(dep_id)
    assert row is not None
    assert row.status == "failed"
    assert row.status_message is not None
    raw_message = row.status_message.lower()
    assert "401" not in raw_message or any(
        phrase in raw_message
        for phrase in ("api key", "lightning ai", "check", "invalid", "rejected")
    ), f"status_message should be human-readable, got: {row.status_message!r}"
    assert len(row.status_message) > 0


@pytest.mark.asyncio
async def test_mixed_hardware_concurrent_limit_409(transport, supported_hf_model, fake_lightning_ai_provider):
    """3-deployment cap applies combined across CPU and GPU (FR-019)."""
    from datetime import UTC, datetime

    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        await _ensure_credentials(client, headers)
        await client.post(
            "/api/lightning/credentials",
            headers=headers,
            json={"lightning_user_id": "fake-lai-uid-123", "api_key": "lai-validkey"},
        )

        session_factory = get_session_factory()
        with session_factory() as db:
            # Seed 2 CPU + 1 GPU = 3 active deployments
            for idx in range(2):
                db.add(DeploymentRow(
                    id=str(uuid.uuid4()),
                    user_id="test_user",
                    hf_model_id=f"some/cpu-model-{idx}",
                    hf_model_display_name=f"CPU Model {idx}",
                    hardware_type="cpu",
                    gcp_project_id=f"llmops-mixed{idx}xxxxx-aaa{idx}",
                    gke_cluster_name="llmops-cluster",
                    gke_region="us-central1",
                    status="running",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ))
            db.add(DeploymentRow(
                id=str(uuid.uuid4()),
                user_id="test_user",
                hf_model_id="some/gpu-model",
                hf_model_display_name="GPU Model",
                hardware_type="gpu",
                lightning_ai_deployment_id="lai-existing",
                status="running",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ))
            db.commit()

        # 4th attempt — either hardware_type should fail
        cpu_resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "cpu"},
        )
        gpu_resp = await client.post(
            "/api/deployments",
            headers=headers,
            json={"hf_model_id": "Qwen/Qwen3-1.7B", "hardware_type": "gpu"},
        )

    assert cpu_resp.status_code == 409
    assert cpu_resp.json()["detail"]["code"] == "concurrent_deployment_limit"
    assert gpu_resp.status_code == 409
    assert gpu_resp.json()["detail"]["code"] == "concurrent_deployment_limit"
