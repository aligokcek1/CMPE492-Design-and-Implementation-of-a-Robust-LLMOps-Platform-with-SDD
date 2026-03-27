from fastapi import APIRouter, HTTPException, Header
from typing import Annotated

from ..models.deployment import MockDeploymentRequest, MockDeploymentResponse
from ..services.mock_gcp import mock_deploy

router = APIRouter()


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.removeprefix("Bearer ")


@router.post("/mock", response_model=MockDeploymentResponse)
async def start_mock_deployment(
    payload: MockDeploymentRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> MockDeploymentResponse:
    _extract_token(authorization)
    try:
        return await mock_deploy(payload.model_repository, payload.resource_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
