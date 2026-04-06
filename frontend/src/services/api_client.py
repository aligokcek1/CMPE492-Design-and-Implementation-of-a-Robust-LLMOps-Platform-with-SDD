import requests
from typing import Any

BACKEND_URL = "http://localhost:8000"


class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


def _raise_for_status(response: requests.Response) -> None:
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise APIError(response.status_code, detail)


def verify_token(token: str) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/auth/verify",
        json={"token": token},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def start_upload(token: str, repository_id: str, uploaded_files: list) -> dict[str, Any]:
    """Send files as multipart form data.

    ``uploaded_files`` is a list of ``(filename, UploadedFile)`` tuples.
    The *filename* may contain path separators (e.g. ``weights/model.bin``)
    to create subdirectories in the target repository.
    """
    multipart_files = [
        ("files", (name, uf.getvalue(), "application/octet-stream"))
        for name, uf in uploaded_files
    ]
    response = requests.post(
        f"{BACKEND_URL}/api/upload/start",
        data={"repository_id": repository_id},
        files=multipart_files,
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
    )
    _raise_for_status(response)
    return response.json()


def list_models(token: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{BACKEND_URL}/api/models",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    _raise_for_status(response)
    return response.json()


def fetch_public_model_info(token: str, repo_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/api/models/public",
        params={"repo_id": repo_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def mock_deploy(token: str, model_repository: str, resource_type: str) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/deployment/mock",
        json={"model_repository": model_repository, "resource_type": resource_type},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    _raise_for_status(response)
    return response.json()
