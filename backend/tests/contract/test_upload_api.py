import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from src.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


def _make_files(names: list[str]) -> list[tuple]:
    return [("files", (name, b"fake content", "application/octet-stream")) for name in names]


@pytest.mark.asyncio
async def test_upload_start_success(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = "commit_abc123"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers={"Authorization": "Bearer hf_valid_token"},
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
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "otheruser/their-model"},
                files=_make_files(["model.bin"]),
                headers={"Authorization": "Bearer hf_valid_token"},
            )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_upload_start_forbidden(transport):
    with patch("src.api.upload.upload_model_folder", new_callable=AsyncMock) as mock_upload:
        mock_upload.side_effect = PermissionError("Token lacks write permission")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/upload/start",
                data={"repository_id": "testuser/my-model"},
                files=_make_files(["model.bin"]),
                headers={"Authorization": "Bearer hf_read_only_token"},
            )
    assert response.status_code == 403
