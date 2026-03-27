import os
import shutil
import tempfile
import uuid
from fastapi import APIRouter, Form, HTTPException, Header, UploadFile, File
from typing import Annotated

from ..models.upload import UploadStartResponse
from ..services.huggingface import upload_model_folder

router = APIRouter()


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.removeprefix("Bearer ")


@router.post("/start", response_model=UploadStartResponse)
async def start_upload(
    repository_id: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    authorization: Annotated[str | None, Header()] = None,
) -> UploadStartResponse:
    token = _extract_token(authorization)
    session_id = str(uuid.uuid4())

    tmp_dir = tempfile.mkdtemp(prefix="llmops_upload_")
    try:
        for upload_file in files:
            filename = os.path.basename(upload_file.filename or "unnamed_file")
            dest = os.path.join(tmp_dir, filename)
            content = await upload_file.read()
            with open(dest, "wb") as fh:
                fh.write(content)

        await upload_model_folder(
            token=token,
            local_path=tmp_dir,
            repo_id=repository_id,
        )
    except PermissionError as exc:
        msg = str(exc)
        if "conflict" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return UploadStartResponse(session_id=session_id)
