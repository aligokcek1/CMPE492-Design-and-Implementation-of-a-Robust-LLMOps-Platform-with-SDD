from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.session_store import session_store


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
    payload = response.json()
    assert payload["username"] == "test_user"
    assert "session_token" in payload
    assert "expires_at" in payload
    assert payload["inactivity_timeout_seconds"] == 86400


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


@pytest.mark.asyncio
async def test_get_session_status_success(transport):
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
            session_token = login.json()["session_token"]
            response = await client.get(
                "/api/auth/session",
                headers={"Authorization": f"Bearer {session_token}"},
            )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "test_user"
    assert data["session_token"] == session_token


@pytest.mark.asyncio
async def test_get_session_status_invalid_token(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/auth/session",
            headers={"Authorization": "Bearer invalid_session"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_success(transport):
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
            session_token = login.json()["session_token"]
            response = await client.post(
                "/api/auth/logout",
                headers={"Authorization": f"Bearer {session_token}"},
            )
            after = await client.get(
                "/api/auth/session",
                headers={"Authorization": f"Bearer {session_token}"},
            )
    assert response.status_code == 200
    assert response.json()["status"] == "logged_out"
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_get_session_status_expired_semantic_payload(transport):
    with patch("src.api.auth.verify_hf_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = "test_user"
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post("/api/auth/verify", json={"token": "hf_valid_token"})
            session_token = login.json()["session_token"]
            session_store._sessions[session_token].expires_at = datetime.now(UTC) - timedelta(seconds=1)  # noqa: SLF001
            response = await client.get(
                "/api/auth/session",
                headers={"Authorization": f"Bearer {session_token}"},
            )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "session_expired"
