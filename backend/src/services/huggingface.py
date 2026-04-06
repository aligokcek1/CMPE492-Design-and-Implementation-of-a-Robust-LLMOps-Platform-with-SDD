import asyncio
import os
from huggingface_hub import HfApi
from huggingface_hub.utils import HfHubHTTPError
from typing import Any

from ..models.upload import FolderUploadResult


def _get_api(token: str) -> HfApi:
    return HfApi(token=token)


async def verify_hf_token(token: str) -> str:
    """Verify a Hugging Face token and return the username."""
    loop = asyncio.get_event_loop()
    try:
        api = _get_api(token)
        user_info = await loop.run_in_executor(None, api.whoami)
        return user_info["name"]
    except Exception as exc:
        raise ValueError(f"Invalid or unauthorized Hugging Face token: {exc}") from exc


async def upload_model_folder(
    token: str,
    local_path: str,
    repo_id: str,
) -> list[FolderUploadResult]:
    """Upload a local directory to a Hugging Face repository.

    Iterates over each subdirectory found under local_path and calls
    upload_folder once per subdirectory with path_in_repo set to the
    folder name. Root-level files are uploaded with path_in_repo=None.
    Each folder upload is isolated so one failure does not abort the rest.
    """
    loop = asyncio.get_event_loop()
    api = _get_api(token)

    def _create_repo():
        api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True)

    await loop.run_in_executor(None, _create_repo)

    results: list[FolderUploadResult] = []
    entries = sorted(os.listdir(local_path))
    has_root_files = any(
        os.path.isfile(os.path.join(local_path, e)) for e in entries
    )
    subdirs = [e for e in entries if os.path.isdir(os.path.join(local_path, e))]

    if has_root_files and not subdirs:
        def _upload_flat():
            return api.upload_folder(
                folder_path=local_path,
                repo_id=repo_id,
                repo_type="model",
            )
        try:
            await loop.run_in_executor(None, _upload_flat)
        except HfHubHTTPError as exc:
            if exc.response.status_code == 409:
                raise PermissionError(f"Repository conflict for {repo_id}: {exc}") from exc
            if exc.response.status_code == 403:
                raise PermissionError(f"Token lacks write permission for {repo_id}: {exc}") from exc
            raise
        return results

    if has_root_files:
        def _upload_root_files():
            return api.upload_folder(
                folder_path=local_path,
                repo_id=repo_id,
                repo_type="model",
                allow_patterns=["*"],
                ignore_patterns=["*/"],
            )
        try:
            await loop.run_in_executor(None, _upload_root_files)
        except Exception:
            pass

    for folder_name in subdirs:
        subdir = os.path.join(local_path, folder_name)

        def _upload_subdir(sd=subdir, fn=folder_name):
            return api.upload_folder(
                folder_path=sd,
                repo_id=repo_id,
                repo_type="model",
                path_in_repo=fn,
            )

        try:
            await loop.run_in_executor(None, _upload_subdir)
            results.append(FolderUploadResult(
                folder_name=folder_name, status="success",
            ))
        except HfHubHTTPError as exc:
            if exc.response.status_code == 409:
                raise PermissionError(f"Repository conflict for {repo_id}: {exc}") from exc
            if exc.response.status_code == 403:
                raise PermissionError(f"Token lacks write permission for {repo_id}: {exc}") from exc
            results.append(FolderUploadResult(
                folder_name=folder_name, status="error", error=str(exc),
            ))
        except Exception as exc:
            results.append(FolderUploadResult(
                folder_name=folder_name, status="error", error=str(exc),
            ))

    return results


async def fetch_public_model_info(repo_id: str) -> dict[str, Any]:
    """Fetch metadata for a public HF model repository (no auth required).

    Lets RepositoryNotFoundError and HfHubHTTPError propagate to the caller.
    """
    loop = asyncio.get_event_loop()
    api = HfApi()

    def _fetch():
        info = api.model_info(repo_id, token=None)
        siblings = info.siblings or []
        file_count = len(siblings)
        sizes = [s.size for s in siblings if s.size is not None]
        size_bytes = sum(sizes) if len(sizes) == len(siblings) else None
        return {
            "repo_id": info.modelId or repo_id,
            "author": info.author or repo_id.split("/")[0],
            "description": getattr(info, "card_data", None)
            and getattr(info.card_data, "description", None),
            "file_count": file_count,
            "size_bytes": size_bytes,
        }

    return await loop.run_in_executor(None, _fetch)


async def list_user_models(token: str) -> list[dict[str, Any]]:
    """List all model repositories owned by the authenticated user."""
    loop = asyncio.get_event_loop()
    api = _get_api(token)

    def _list():
        user_info = api.whoami()
        username = user_info["name"]
        repos = api.list_models(author=username)
        return [
            {"id": repo.id, "name": repo.modelId}
            for repo in repos
        ]

    return await loop.run_in_executor(None, _list)
