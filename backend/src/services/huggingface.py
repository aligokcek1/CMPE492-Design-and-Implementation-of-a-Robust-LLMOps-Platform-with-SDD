import asyncio
from huggingface_hub import HfApi
from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError
from typing import Any


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
) -> str:
    """Upload a local directory to a Hugging Face repository.

    Uses upload_folder which handles chunked/resumable uploads natively,
    supporting large files without loading them fully into memory.
    """
    loop = asyncio.get_event_loop()
    api = _get_api(token)

    def _upload():
        api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True)
        return api.upload_folder(
            folder_path=local_path,
            repo_id=repo_id,
            repo_type="model",
        )

    try:
        commit_info = await loop.run_in_executor(None, _upload)
        return str(commit_info)
    except HfHubHTTPError as exc:
        if exc.response.status_code == 409:
            raise PermissionError(f"Repository conflict for {repo_id}: {exc}") from exc
        if exc.response.status_code == 403:
            raise PermissionError(f"Token lacks write permission for {repo_id}: {exc}") from exc
        raise


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
