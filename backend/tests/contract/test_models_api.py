from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

from src.main import app
from src.services.session_store import session_store


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _session_auth_headers(client: AsyncClient) -> dict[str, str]:
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
    token = login.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_models_success(transport):
    mock_models = [
        {"id": "testuser/gpt2-finetuned", "name": "testuser/gpt2-finetuned"},
        {"id": "testuser/llama-custom", "name": "testuser/llama-custom"},
    ]
    with patch("src.api.models.list_user_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_models
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.get(
                "/api/models",
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["id"] == "testuser/gpt2-finetuned"


@pytest.mark.asyncio
async def test_list_models_missing_token(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/models")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_models_empty(transport):
    with patch("src.api.models.list_user_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.get(
                "/api/models",
                headers=headers,
            )
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# T016: GET /api/models/public — valid public repo → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_public_model_success(transport):
    mock_info = {
        "repo_id": "google-bert/bert-base-uncased",
        "author": "google-bert",
        "description": "Pretrained BERT model",
        "file_count": 12,
        "size_bytes": 440473133,
    }
    with patch("src.api.models.fetch_public_model_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_info
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "google-bert/bert-base-uncased"},
                headers=headers,
            )
    assert response.status_code == 200
    data = response.json()
    assert data["repo_id"] == "google-bert/bert-base-uncased"
    assert data["author"] == "google-bert"
    assert data["file_count"] == 12
    assert data["size_bytes"] == 440473133


# ---------------------------------------------------------------------------
# T017: GET /api/models/public — not found → 404
# ---------------------------------------------------------------------------
def _make_repo_not_found_error(msg: str = "not found") -> RepositoryNotFoundError:
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.headers = {}
    return RepositoryNotFoundError(msg, response=mock_resp)


@pytest.mark.asyncio
async def test_get_public_model_not_found(transport):
    with patch("src.api.models.fetch_public_model_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = _make_repo_not_found_error()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "nonexistent/model"},
                headers=headers,
            )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# T018: GET /api/models/public — private repo → 403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_public_model_private(transport):
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.headers = {}
    with patch("src.api.models.fetch_public_model_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = HfHubHTTPError("Forbidden", response=mock_response)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "private-user/private-model"},
                headers=headers,
            )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# T019: GET /api/models/public — invalid format → 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_public_model_invalid_format(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _session_auth_headers(client)
        response = await client.get(
            "/api/models/public",
            params={"repo_id": "justname"},
            headers=headers,
        )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# T020: GET /api/models/public — missing token → 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_public_model_missing_token(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/models/public",
            params={"repo_id": "bert-base-uncased"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_models_expired_session_returns_semantic_code(transport):
    with patch("src.api.models.list_user_models", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _session_auth_headers(client)
            session_token = headers["Authorization"].removeprefix("Bearer ")
            session_store._sessions[session_token].expires_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001
            response = await client.get("/api/models", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "session_expired"
