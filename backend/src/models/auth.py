from pydantic import BaseModel, field_validator
import re


class HuggingFaceAuth(BaseModel):
    access_token: str
    username: str = ""

    @field_validator("access_token")
    @classmethod
    def token_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("access_token must not be empty")
        return v.strip()


class TokenVerifyRequest(BaseModel):
    token: str


class TokenVerifyResponse(BaseModel):
    username: str
