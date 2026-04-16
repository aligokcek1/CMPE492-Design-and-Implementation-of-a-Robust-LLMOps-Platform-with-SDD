from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..models.gcp_credentials import GCPCredentialsRequest, GCPCredentialsStatus
from ..services.credentials_store import CredentialsError, credentials_store
from ..services.gcp_provider import GCPProvider, GCPProviderError
from ..services.session_store import SessionContext
from .auth_helpers import require_session
from .dependencies import get_gcp_provider

router = APIRouter()


def _to_response(status_obj) -> GCPCredentialsStatus:
    return GCPCredentialsStatus(
        configured=status_obj.configured,
        service_account_email=status_obj.service_account_email,
        gcp_project_id_of_sa=status_obj.gcp_project_id_of_sa,
        billing_account_id=status_obj.billing_account_id,
        validation_status=status_obj.validation_status,
        validation_error_message=status_obj.validation_error_message,
        last_validated_at=status_obj.last_validated_at,
    )


@router.get("", response_model=GCPCredentialsStatus)
async def get_credentials_status(
    session: SessionContext = Depends(require_session),
) -> GCPCredentialsStatus:
    status_obj = await credentials_store.get_status(user_id=session.username)
    return _to_response(status_obj)


@router.post("", response_model=GCPCredentialsStatus)
async def save_credentials(
    payload: GCPCredentialsRequest,
    session: SessionContext = Depends(require_session),
    provider: GCPProvider = Depends(get_gcp_provider),
) -> GCPCredentialsStatus:
    try:
        status_obj = await credentials_store.save(
            user_id=session.username,
            sa_json=payload.service_account_json,
            billing_account_id=payload.billing_account_id,
            provider=provider,
        )
    except GCPProviderError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return _to_response(status_obj)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    session: SessionContext = Depends(require_session),
) -> Response:
    try:
        await credentials_store.delete(user_id=session.username)
    except CredentialsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
