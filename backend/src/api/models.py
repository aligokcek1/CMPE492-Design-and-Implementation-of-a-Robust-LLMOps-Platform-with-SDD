import re
from fastapi import APIRouter, HTTPException, Header
from typing import Annotated, Any

from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

from ..models.upload import PublicModelInfoResponse
from ..services.huggingface import list_user_models, fetch_public_model_info

router = APIRouter()

_REPO_ID_RE = re.compile(r"^[\w\-\.]+/[\w\-\.]+$")


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.removeprefix("Bearer ")


@router.get("/models", response_model=list[dict])
async def get_models(
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, Any]]:
    token = _extract_token(authorization)
    try:
        return await list_user_models(token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/models/public", response_model=PublicModelInfoResponse)
async def get_public_model(
    repo_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PublicModelInfoResponse:
    _extract_token(authorization)

    if not _REPO_ID_RE.match(repo_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid repo_id format. Expected owner/repo-name.",
        )

    try:
        info = await fetch_public_model_info(repo_id)
        return PublicModelInfoResponse(**info)
    except RepositoryNotFoundError:
        raise HTTPException(status_code=404, detail="Repository not found")
    except HfHubHTTPError as exc:
        if hasattr(exc, "response") and exc.response is not None and exc.response.status_code == 403:
            raise HTTPException(status_code=403, detail="Repository is private")
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
