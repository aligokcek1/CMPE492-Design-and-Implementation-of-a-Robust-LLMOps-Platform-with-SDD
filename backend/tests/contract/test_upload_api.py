from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.models.upload import FolderUploadResult


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _make_files(names: list[str]) -> list[tuple]:
    return [("files", (name, b"fake content", "application/octet-stream")) for name in names]


async def _session_auth_headers(client: AsyncClient) -> dict[str, str]:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# T004: Multi-folder upload — two folder groups succeed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_multi_folder_success(transport):
    folder_results = [
        FolderUploadResult(folder_name="weights", status="success"),
        FolderUploadResult(folder_name="tokenizer", status="success"),
    ]
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = folder_results
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["weights/model.bin", "tokenizer/vocab.json"]),
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert len(data["folder_results"]) == 2
    assert data["folder_results"][0]["folder_name"] == "weights"
    mock_upload.assert_called_once()


# ---------------------------------------------------------------------------
# T005: Path traversal in filename → 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_path_traversal_rejected(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["../../etc/passwd"]),
                headers=headers,
            )
    assert response.status_code == 400
    mock_upload.assert_not_called()


# ---------------------------------------------------------------------------
# T006: Mixed root and folder files → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_mixed_root_and_folder_files(transport):
    folder_results = [
        FolderUploadResult(folder_name="weights", status="success"),
    ]
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = folder_results
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["weights/model.bin", "README.md"]),
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data


# ---------------------------------------------------------------------------
# T007: Empty folder name prefix → falls back to root, not rejected → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_empty_folder_name_falls_back_to_root(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["/file.bin"]),
                headers=headers,
            )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# T010b: Total upload size exceeds limit → 413
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_size_limit_exceeded(transport):
    with patch("src.api.upload.MAX_UPLOAD_BYTES", 10):
        with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _session_auth_headers(client)
                response = await client.post(
                    "/api/upload/start",
                    data={"repository_id": "testuser/my-model"},
                    files=_make_files(["big.bin"]),
                    headers=headers,
                )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_upload_start_success(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = "commit_abc123"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data


@pytest.mark.asyncio
async def test_upload_start_missing_token(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/upload/start",
            data={"repository_id": "testuser/my-model"},
            files=_make_files(["model.bin"]),
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_start_conflict(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.side_effect = PermissionError("Repository conflict")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "otheruser/their-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_upload_start_forbidden(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.side_effect = PermissionError("Token lacks write permission")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_idempotency_replay_returns_same_response(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            headers["X-Idempotency-Key"] = "retry-upload-1"
            first = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
            second = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert mock_upload.call_count == 1


@pytest.mark.asyncio
async def test_upload_idempotency_conflict_on_different_payload(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            headers["X-Idempotency-Key"] = "retry-upload-2"
            first = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers=headers,
            )
            second = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["other.bin"]),
                headers=headers,
            )
    assert first.status_code == 200
    assert second.status_code == 409
