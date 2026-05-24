"""Contract tests for deployment metrics API (feature 010)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.services.metrics_store import metrics_store


async def _session_auth_headers(client: AsyncClient) -> dict[str, str]:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_deployment(
    user_id: str,
    *,
    status: str = "running",
    hardware_type: str = "cpu",
    deployment_id: str | None = None,
) -> str:
    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = deployment_id or str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        if hardware_type == "cpu":
            db.add(
                DeploymentRow(
                    id=dep_id,
                    user_id=user_id,
                    hf_model_id="Qwen/Qwen3-1.7B",
                    hf_model_display_name="Qwen3 1.7B",
                    hardware_type="cpu",
                    gcp_project_id=f"llmops-{dep_id.replace('-', '')[:12]}",
                    gke_cluster_name="llmops-cluster",
                    gke_region="us-central1",
                    status=status,
                    endpoint_url="http://1.2.3.4:80" if status == "running" else None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        else:
            db.add(
                DeploymentRow(
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
                )
            )
        db.commit()
    return dep_id


def _seed_monitoring(deployment_id: str, user_id: str = "test_user") -> None:
    metrics_store.create_active(
        deployment_id=deployment_id,
        user_id=user_id,
        scrape_job=f"deployment-{deployment_id}",
        grafana_datasource_uid=f"dep-{deployment_id[:8]}",
        grafana_dashboard_uid=f"dash-{deployment_id[:8]}",
    )


@pytest.mark.asyncio
async def test_metrics_running_with_monitoring_returns_summary(transport):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["deployment_id"] == dep_id
    assert data["summary"]["ttft_avg_seconds"] is not None
    assert data["summary"]["throughput_value"] is not None
    assert data["empty"] is False


@pytest.mark.asyncio
async def test_metrics_empty_when_no_traffic(transport, fake_metrics_query_client):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    fake_metrics_query_client.set_empty(True)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["empty"] is True


@pytest.mark.asyncio
async def test_metrics_non_running_returns_404(transport):
    dep_id = _seed_deployment("test_user", status="deploying")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_metrics_deleted_returns_404(transport):
    dep_id = _seed_deployment("test_user", status="deleted")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_metrics_foreign_user_returns_403(transport):
    dep_id = _seed_deployment("someone_else")
    _seed_monitoring(dep_id, user_id="someone_else")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_metrics_prometheus_unreachable_returns_503(transport, fake_metrics_query_client):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    fake_metrics_query_client.set_unreachable(True)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_metrics_without_monitoring_row_returns_503(transport):
    dep_id = _seed_deployment("test_user")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    message = detail.get("message", detail) if isinstance(detail, dict) else detail
    assert "provisioned" in str(message).lower()


@pytest.mark.asyncio
async def test_metrics_range_query_param(transport):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        for range_val in ("1h", "24h", "7d"):
            resp = await client.get(
                f"/api/deployments/{dep_id}/metrics?range={range_val}",
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["range"] == range_val
            assert isinstance(data["series"]["ttft"], list)
            assert isinstance(data["series"]["throughput"], list)


@pytest.mark.asyncio
async def test_metrics_summary_includes_p95_and_failed_exclusion(transport, fake_metrics_query_client):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    data = resp.json()
    assert data["summary"]["ttft_p95_seconds"] is not None
    assert data["summary"]["failed_requests_excluded"] is True


@pytest.mark.asyncio
async def test_metrics_cpu_hardware_available_gpu_na(transport):
    dep_id = _seed_deployment("test_user", hardware_type="cpu")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    hw = resp.json()["series"]["hardware"]
    assert hw["cpu_utilization"]["available"] is True
    assert hw["gpu_utilization"]["available"] is False


@pytest.mark.asyncio
async def test_metrics_gpu_without_gpu_series_returns_na(transport):
    dep_id = _seed_deployment("test_user", hardware_type="gpu")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics", headers=headers)
    data = resp.json()
    gpu = data["series"]["hardware"]["gpu_utilization"]
    assert gpu["available"] is False
    assert gpu["reason"] == "not_available_for_this_deployment_type"
    assert data["summary"]["ttft_avg_seconds"] is not None


@pytest.mark.asyncio
async def test_grafana_link_for_running_deployment(transport):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics/grafana", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "redirect_url" in data
    assert "expires_at" in data
    assert "token=" in data["redirect_url"]


@pytest.mark.asyncio
async def test_grafana_link_deleted_returns_404(transport):
    dep_id = _seed_deployment("test_user", status="deleted")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics/grafana", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_grafana_link_foreign_user_returns_403(transport):
    dep_id = _seed_deployment("someone_else")
    _seed_monitoring(dep_id, user_id="someone_else")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        resp = await client.get(f"/api/deployments/{dep_id}/metrics/grafana", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_grafana_redirect_valid_token_302(transport):
    dep_id = _seed_deployment("test_user")
    _seed_monitoring(dep_id)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        headers = await _session_auth_headers(client)
        link_resp = await client.get(f"/api/deployments/{dep_id}/metrics/grafana", headers=headers)
        redirect_url = link_resp.json()["redirect_url"]
        token = redirect_url.split("token=")[1]
        resp = await client.get(f"/api/metrics/grafana/redirect?token={token}")
    assert resp.status_code == 302
    assert "/d/dash-" in resp.headers["location"]


@pytest.mark.asyncio
async def test_grafana_redirect_tampered_token_returns_403(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/grafana/redirect?token=not-a-valid-token")
    assert resp.status_code == 403
