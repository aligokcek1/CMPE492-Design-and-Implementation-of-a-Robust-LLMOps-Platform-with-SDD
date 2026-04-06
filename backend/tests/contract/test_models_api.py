import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock

from huggingface_hub.utils import RepositoryNotFoundError, HfHubHTTPError

from src.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_list_models_success(transport):
    mock_models = [
        {"id": "testuser/gpt2-finetuned", "name": "testuser/gpt2-finetuned"},
        {"id": "testuser/llama-custom", "name": "testuser/llama-custom"},
    ]
    with patch("src.api.models.list_user_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_models
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/models",
                headers={"Authorization": "Bearer hf_valid_token"},
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
            response = await client.get(
                "/api/models",
                headers={"Authorization": "Bearer hf_valid_token"},
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
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "google-bert/bert-base-uncased"},
                headers={"Authorization": "Bearer hf_valid_token"},
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
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "nonexistent/model"},
                headers={"Authorization": "Bearer hf_valid_token"},
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
            response = await client.get(
                "/api/models/public",
                params={"repo_id": "private-user/private-model"},
                headers={"Authorization": "Bearer hf_valid_token"},
            )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# T019: GET /api/models/public — invalid format → 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_public_model_invalid_format(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/models/public",
            params={"repo_id": "justname"},
            headers={"Authorization": "Bearer hf_valid_token"},
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
