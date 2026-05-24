"""Deployment metrics and Grafana signed redirect endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..api.auth_helpers import require_session
from ..models.metrics import DeploymentMetricsResponse, GrafanaLinkResponse, MetricsRange
from ..services.deployment_store import deployment_store
from ..services.grafana_signed_url import GrafanaSignedUrlError, grafana_signed_url_service
from ..services.metrics_store import metrics_store
from .dependencies import get_metrics_query_service

router = APIRouter()


def _require_running_owned_deployment(deployment_id: str, username: str):
    row = deployment_store.get(deployment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deployment not found.")
    if row.user_id != username:
        raise HTTPException(status_code=403, detail="Deployment belongs to another user.")
    if row.status != "running":
        raise HTTPException(status_code=404, detail="Metrics are only available for running deployments.")
    return row


def _require_active_monitoring(deployment_id: str):
    monitoring = metrics_store.get_for_deployment(deployment_id)
    if monitoring is None or monitoring.status != "active":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_not_provisioned",
                "message": "Monitoring has not been provisioned for this deployment yet.",
            },
        )
    return monitoring


@router.get("/deployments/{deployment_id}/metrics", response_model=DeploymentMetricsResponse)
async def get_deployment_metrics(
    deployment_id: str,
    range: MetricsRange = Query(default=MetricsRange.one_hour),
    session=Depends(require_session),
    query_service=Depends(get_metrics_query_service),
):
    row = _require_running_owned_deployment(deployment_id, session.username)
    _require_active_monitoring(deployment_id)
    result = await query_service.fetch_deployment_metrics(
        deployment_id=deployment_id,
        user_id=session.username,
        hardware_type=row.hardware_type,
        range=range,
    )
    if result.error and result.empty:
        raise HTTPException(status_code=503, detail=result.error)
    return result


@router.get("/deployments/{deployment_id}/metrics/grafana", response_model=GrafanaLinkResponse)
async def get_deployment_grafana_link(
    deployment_id: str,
    session=Depends(require_session),
):
    _require_running_owned_deployment(deployment_id, session.username)
    monitoring = _require_active_monitoring(deployment_id)
    return grafana_signed_url_service.mint(
        deployment_id=deployment_id,
        user_id=session.username,
        dashboard_uid=monitoring.grafana_dashboard_uid,
    )


@router.get("/metrics/grafana/redirect")
async def grafana_redirect(token: str):
    try:
        _deployment_id, _user_id, dashboard_uid = grafana_signed_url_service.validate(token)
    except GrafanaSignedUrlError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    url = grafana_signed_url_service.grafana_dashboard_url(
        dashboard_uid,
        deployment_id=_deployment_id,
        user_id=_user_id,
    )
    return RedirectResponse(url=url, status_code=302)


__all__ = ["router"]
