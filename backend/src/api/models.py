import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

from ..api.auth_helpers import require_session
from ..models.upload import PublicModelInfoResponse
from ..services.huggingface import fetch_public_model_info, list_user_models

router = APIRouter()

_REPO_ID_RE = re.compile(r"^[\w\-\.]+/[\w\-\.]+$")


@router.get("/models", response_model=list[dict])
async def get_models(
    session=Depends(require_session),
) -> list[dict[str, Any]]:
    try:
        return await list_user_models(session.hf_token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/models/public", response_model=PublicModelInfoResponse)
async def get_public_model(
    repo_id: str,
    _session=Depends(require_session),
) -> PublicModelInfoResponse:
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
