import os
import posixpath
import shutil
import tempfile
import uuid
from fastapi import APIRouter, Form, HTTPException, Header, UploadFile, File
from typing import Annotated

from ..models.upload import UploadStartResponse
from ..services.huggingface import upload_model_folder

router = APIRouter()

MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GB


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.removeprefix("Bearer ")


def _sanitise_filename(raw: str) -> str:
    """Return a safe relative path from a raw upload filename.

    Strips leading '/', rejects '..' segments, and normalises the path.
    Returns an empty string only when the input resolves to empty after
    stripping — callers should fall back to a default name.
    """
    stripped = raw.lstrip("/")
    normalised = posixpath.normpath(stripped)
    if normalised == ".":
        return ""
    parts = normalised.split("/")
    if ".." in parts:
        raise HTTPException(
            status_code=400,
            detail=f"Path traversal detected in filename: {raw}",
        )
    return normalised


@router.post("/start", response_model=UploadStartResponse)
async def start_upload(
    repository_id: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    authorization: Annotated[str | None, Header()] = None,
) -> UploadStartResponse:
    token = _extract_token(authorization)
    session_id = str(uuid.uuid4())

    total_size = 0
    file_contents: list[tuple[str, bytes]] = []

    for upload_file in files:
        raw_name = upload_file.filename or "unnamed_file"
        safe_rel = _sanitise_filename(raw_name)
        if not safe_rel:
            safe_rel = "unnamed_file"
        content = await upload_file.read()
        total_size += len(content)
        if total_size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Total upload size exceeds the platform limit",
            )
        file_contents.append((safe_rel, content))

    tmp_dir = tempfile.mkdtemp(prefix="llmops_upload_")
    try:
        for safe_rel, content in file_contents:
            dest = os.path.join(tmp_dir, safe_rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(content)

        folder_results = await upload_model_folder(
            token=token,
            local_path=tmp_dir,
            repo_id=repository_id,
        )
    except HTTPException:
        raise
    except PermissionError as exc:
        msg = str(exc)
        if "conflict" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not isinstance(folder_results, list):
        folder_results = []

    return UploadStartResponse(session_id=session_id, folder_results=folder_results)
