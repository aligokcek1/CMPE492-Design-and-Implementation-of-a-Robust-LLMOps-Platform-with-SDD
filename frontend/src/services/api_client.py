import requests
from typing import Any

BACKEND_URL = "http://localhost:8000"


class APIError(Exception):
    def __init__(self, status_code: int, detail: str, code: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.code = code
        super().__init__(f"API error {status_code}: {detail}")


def _raise_for_status(response: requests.Response) -> None:
    if not response.ok:
        code = None
        try:
            raw_detail = response.json().get("detail", response.text)
            if isinstance(raw_detail, dict):
                code = raw_detail.get("code")
                detail = str(raw_detail.get("message", response.text))
            else:
                detail = str(raw_detail)
        except Exception:
            detail = response.text
        raise APIError(response.status_code, detail, code=code)


def verify_token(token: str) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/auth/verify",
        json={"token": token},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def get_session_status(session_token: str) -> dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/api/auth/session",
        headers={"Authorization": f"Bearer {session_token}"},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def logout(session_token: str) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/auth/logout",
        headers={"Authorization": f"Bearer {session_token}"},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def _session_headers(session_token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {session_token}"}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


def start_upload(
    session_token: str,
    repository_id: str,
    uploaded_files: list,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
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
        headers=_session_headers(session_token, idempotency_key),
        timeout=300,
    )
    _raise_for_status(response)
    return response.json()


def list_models(session_token: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{BACKEND_URL}/api/models",
        headers=_session_headers(session_token),
        timeout=30,
    )
    _raise_for_status(response)
    return response.json()


def fetch_public_model_info(session_token: str, repo_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/api/models/public",
        params={"repo_id": repo_id},
        headers=_session_headers(session_token),
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def mock_deploy(
    session_token: str,
    model_repository: str,
    resource_type: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/deployment/mock",
        json={"model_repository": model_repository, "resource_type": resource_type},
        headers=_session_headers(session_token, idempotency_key),
        timeout=60,
    )
    _raise_for_status(response)
    return response.json()


def save_gcp_credentials(
    session_token: str,
    service_account_json: str,
    billing_account_id: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{BACKEND_URL}/api/gcp/credentials",
        json={
            "service_account_json": service_account_json,
            "billing_account_id": billing_account_id,
        },
        headers=_session_headers(session_token),
        timeout=30,
    )
    _raise_for_status(response)
    return response.json()


def get_gcp_credentials_status(session_token: str) -> dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/api/gcp/credentials",
        headers=_session_headers(session_token),
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()


def delete_gcp_credentials(session_token: str) -> None:
    response = requests.delete(
        f"{BACKEND_URL}/api/gcp/credentials",
        headers=_session_headers(session_token),
        timeout=30,
    )
    _raise_for_status(response)
