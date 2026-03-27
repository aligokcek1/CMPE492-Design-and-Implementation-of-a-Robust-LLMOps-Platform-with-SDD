import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

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
