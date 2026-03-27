from fastapi import APIRouter, HTTPException

from ..models.auth import TokenVerifyRequest, TokenVerifyResponse
from ..services.huggingface import verify_hf_token

router = APIRouter()


@router.post("/verify", response_model=TokenVerifyResponse)
async def verify_token(payload: TokenVerifyRequest) -> TokenVerifyResponse:
    try:
        username = await verify_hf_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return TokenVerifyResponse(username=username)
