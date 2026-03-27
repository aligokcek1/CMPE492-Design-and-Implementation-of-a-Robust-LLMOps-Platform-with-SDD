from fastapi import APIRouter, HTTPException, Header
from typing import Annotated, Any

from ..services.huggingface import list_user_models

router = APIRouter()


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
