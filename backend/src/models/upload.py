from enum import Enum
from pydantic import BaseModel, field_validator
import re


class UploadStatus(str, Enum):
    pending = "pending"
    uploading = "uploading"
    completed = "completed"
    failed = "failed"


class LocalModelSession(BaseModel):
    session_id: str = ""
    local_path: str = ""
    repository_name: str
    status: UploadStatus = UploadStatus.pending
    progress: float = 0.0

    @field_validator("repository_name")
    @classmethod
    def validate_repo_name(cls, v: str) -> str:
        if not re.match(r"^[\w][\w\-\.\/]*$", v):
            raise ValueError(
                "repository_name must be valid Hugging Face repository ID (e.g. username/my-model)"
            )
        return v

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("progress must be between 0.0 and 1.0")
        return v


class UploadStartRequest(BaseModel):
    repository_id: str
    files_metadata: list[str] = []


class FolderUploadResult(BaseModel):
    folder_name: str
    status: str
    error: str | None = None


class UploadStartResponse(BaseModel):
    session_id: str
    folder_results: list[FolderUploadResult] = []


class PublicModelInfoResponse(BaseModel):
    repo_id: str
    author: str
    description: str | None = None
    file_count: int
    size_bytes: int | None = None
