import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from src.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_verify_token_success(transport):
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/auth/verify",
                json={"token": "hf_valid_token_123"},
            )
    assert response.status_code == 200
    assert response.json() == {"username": "test_user"}


@pytest.mark.asyncio
async def test_verify_token_invalid(transport):
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.side_effect = ValueError("Invalid token")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/auth/verify",
                json={"token": "invalid_token"},
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_verify_token_missing_body(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/auth/verify", json={})
    assert response.status_code == 422
