from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from huggingface_hub.utils import RepositoryNotFoundError

from ..api.auth_helpers import require_session
from ..api.dependencies import get_gcp_provider
from ..models.deployment import (
    Deployment,
    DeploymentDetail,
    DeployRequest,
    GkeDeploymentStatus,
    MockDeploymentRequest,
    MockDeploymentResponse,
)
from ..services import hf_models, inference_proxy
from ..services.credentials_store import credentials_store
from ..services.deployment_orchestrator import deployment_orchestrator
from ..services.deployment_store import DeploymentError, deployment_store
from ..services.gcp_provider import GCPProvider
from ..services.inference_proxy import InferenceProxyError
from ..services.mock_gcp import mock_deploy
from ..services.session_store import SessionError, session_store

logger = logging.getLogger("llmops.api.deployment")

router = APIRouter()

# --------------------------------------------------------------------------- #
# Legacy personal-repo mock deploy (feature 004/005/006) — retained per FR-010 #
# --------------------------------------------------------------------------- #


@router.post("/mock", response_model=MockDeploymentResponse)
async def start_mock_deployment(
    payload: MockDeploymentRequest,
    idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
    session=Depends(require_session),
) -> MockDeploymentResponse:
    request_fingerprint = f"{payload.model_repository}|{payload.resource_type.value}"
    try:
        replay = session_store.check_idempotency(
            username=session.username,
            operation_type="deploy",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
    except SessionError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    if replay is not None:
        return MockDeploymentResponse(**replay.response_body)

    try:
        response = await mock_deploy(payload.model_repository, payload.resource_type)
        session_store.store_idempotency_result(
            username=session.username,
            operation_type="deploy",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            status_code=200,
            response_body=response.model_dump(),
        )
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# US2 — real public-model deployment (feature 007)                             #
# --------------------------------------------------------------------------- #

real_router = APIRouter()


def _to_deployment_response(row) -> Deployment:
    return Deployment(
        id=row.id,
        hf_model_id=row.hf_model_id,
        hf_model_display_name=row.hf_model_display_name,
        status=GkeDeploymentStatus(row.status),
        status_message=row.status_message,
        endpoint_url=row.endpoint_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_detail_response(row) -> DeploymentDetail:
    base = _to_deployment_response(row)
    console_url = (
        f"https://console.cloud.google.com/kubernetes/clusters/details/"
        f"{row.gke_region}/{row.gke_cluster_name}?project={row.gcp_project_id}"
    )
    return DeploymentDetail(
        **base.model_dump(),
        gcp_project_id=row.gcp_project_id,
        gke_cluster_name=row.gke_cluster_name,
        gke_region=row.gke_region,
        gcp_console_url=console_url,
    )


async def _preflight_credentials(user_id: str) -> None:
    status = await credentials_store.get_status(user_id=user_id)
    if not status.configured:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "credentials_missing",
                "message": "No GCP credentials configured. Set them up before deploying.",
            },
        )
    if status.validation_status == "invalid":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "credentials_invalid",
                "message": (
                    "Your stored GCP credentials are invalid. Update them before "
                    "creating new deployments."
                ),
            },
        )


@real_router.post("", response_model=Deployment, status_code=202)
async def create_deployment(
    payload: DeployRequest,
    session=Depends(require_session),
    provider: GCPProvider = Depends(get_gcp_provider),
) -> Deployment:
    await _preflight_credentials(session.username)

    try:
        is_supported, pipeline_tag, reason = await hf_models.is_supported_text_generation_model(
            payload.hf_model_id
        )
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "model_not_found",
                "message": str(exc),
            },
        ) from exc

    if not is_supported:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_model",
                "message": reason,
                "pipeline_tag": pipeline_tag,
            },
        )

    display_name = await hf_models.get_display_name(payload.hf_model_id)

    try:
        row = deployment_store.create(
            user_id=session.username,
            hf_model_id=payload.hf_model_id,
            hf_model_display_name=display_name,
            force=payload.force,
        )
    except DeploymentError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "message": exc.message,
                "require_confirmation": exc.require_confirmation,
            },
        ) from exc

    # Fire-and-forget orchestrator. Tests exercise the orchestrator directly,
    # so the background task running here is a no-op for most contract tests
    # (which assert the 202 + DB row and return).
    deployment_orchestrator.schedule(deployment_id=row.id, provider=provider)

    return _to_deployment_response(row)


@real_router.get("", response_model=list[Deployment])
async def list_deployments(
    session=Depends(require_session),
) -> list[Deployment]:
    rows = deployment_store.list_by_user(user_id=session.username)
    return [_to_deployment_response(row) for row in rows]


@real_router.get("/{deployment_id}", response_model=DeploymentDetail)
async def get_deployment(
    deployment_id: str,
    session=Depends(require_session),
) -> DeploymentDetail:
    row = deployment_store.get(deployment_id)
    if row is None or row.user_id != session.username:
        raise HTTPException(status_code=404, detail="Deployment not found.")
    return _to_detail_response(row)


@real_router.delete("/{deployment_id}", response_model=Deployment, status_code=202)
async def delete_deployment(
    deployment_id: str,
    session=Depends(require_session),
    provider: GCPProvider = Depends(get_gcp_provider),
) -> Deployment:
    row = deployment_store.get(deployment_id)
    if row is None or row.user_id != session.username:
        raise HTTPException(status_code=404, detail="Deployment not found.")

    # Preflight: credentials must still be valid (FR-015).
    cred_status = await credentials_store.get_status(user_id=session.username)
    if cred_status.validation_status == "invalid":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "credentials_invalid",
                "message": (
                    "Your GCP credentials are invalid. Update them before deleting deployments. "
                    "Running deployments remain unaffected until you delete them manually here."
                ),
            },
        )

    # Fire-and-forget teardown. Contract tests assert the 202 + updated status.
    # The orchestrator drives the state machine synchronously-ish in tests.
    await deployment_orchestrator.request_deletion(
        deployment_id=deployment_id,
        provider=provider,
    )

    updated = deployment_store.get(deployment_id)
    if updated is None:
        # hard_delete (lost → deleted direct path)
        return Deployment(
            id=deployment_id,
            hf_model_id=row.hf_model_id,
            hf_model_display_name=row.hf_model_display_name,
            status=GkeDeploymentStatus.deleted,
            status_message="Removed.",
            endpoint_url=None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    return _to_deployment_response(updated)


@real_router.post("/{deployment_id}/inference")
async def deployment_inference(
    deployment_id: str,
    body: dict,
    session=Depends(require_session),
):
    import httpx

    row = deployment_store.get(deployment_id)
    if row is None or row.user_id != session.username:
        raise HTTPException(status_code=404, detail="Deployment not found.")

    if row.status != "running":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_running",
                "message": f"Deployment is in status '{row.status}', cannot accept inference requests yet.",
            },
        )
    if not row.endpoint_url:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_running",
                "message": "Deployment has no endpoint URL yet.",
            },
        )

    try:
        return await inference_proxy.forward(endpoint_url=row.endpoint_url, body=body)
    except httpx.ReadTimeout as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "upstream_timeout",
                "message": (
                    "Model did not respond within 120 seconds. This is the configured "
                    "platform hard timeout (SC-008). You may retry."
                ),
            },
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_unreachable",
                "message": f"Could not reach the model endpoint: {exc}",
            },
        ) from exc
    except InferenceProxyError as exc:
        raise HTTPException(
            status_code=exc.status_code if 400 <= exc.status_code < 600 else 502,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@real_router.post("/{deployment_id}/dismiss", status_code=204)
async def dismiss_deployment(
    deployment_id: str,
    session=Depends(require_session),
):
    from fastapi import Response

    row = deployment_store.get(deployment_id)
    if row is None or row.user_id != session.username:
        raise HTTPException(status_code=404, detail="Deployment not found.")

    if row.status != "lost":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_lost",
                "message": (
                    "Only deployments in the 'lost' state can be dismissed. "
                    "Use DELETE for other statuses."
                ),
            },
        )

    deployment_store.hard_delete(deployment_id)
    return Response(status_code=204)


__all__ = ["router", "real_router"]
