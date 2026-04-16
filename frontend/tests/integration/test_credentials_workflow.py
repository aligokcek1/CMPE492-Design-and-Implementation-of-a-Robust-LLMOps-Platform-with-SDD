"""Frontend integration test for the GCP credentials flow (US1)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest


APP_MODULE = "src/app.py"


@pytest.fixture
def authed_at():
    at = AppTest.from_file(APP_MODULE, default_timeout=30)
    at.session_state["session_token"] = "session_abc"
    at.session_state["hf_username"] = "alice"
    at.session_state["_session_checked"] = True
    return at


def _mock_response(json_data: dict, ok: bool = True, status_code: int = 200) -> MagicMock:
    resp = MagicMock(ok=ok, status_code=status_code)
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def test_credentials_form_renders_empty_state(authed_at):
    with patch("src.services.api_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"configured": False})
        authed_at.run()

    assert not authed_at.exception
    assert any(
        "No GCP credentials configured yet" in _val(el)
        for el in authed_at.info
    )


def test_credentials_form_shows_configured_status(authed_at):
    with patch("src.services.api_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response({
            "configured": True,
            "service_account_email": "sa@proj.iam.gserviceaccount.com",
            "gcp_project_id_of_sa": "my-sa-project",
            "billing_account_id": "billingAccounts/ABCDEF-012345-67890X",
            "validation_status": "valid",
            "last_validated_at": "2026-04-16T12:00:00Z",
            "validation_error_message": None,
        })
        authed_at.run()

    assert not authed_at.exception
    assert any(
        "valid" in _val(el).lower() and "configured" in _val(el).lower()
        for el in authed_at.success
    )


def test_credentials_form_shows_invalid_warning(authed_at):
    with patch("src.services.api_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response({
            "configured": True,
            "service_account_email": "sa@proj.iam.gserviceaccount.com",
            "gcp_project_id_of_sa": "my-sa-project",
            "billing_account_id": "billingAccounts/ABCDEF-012345-67890X",
            "validation_status": "invalid",
            "last_validated_at": "2026-04-16T12:00:00Z",
            "validation_error_message": "permission denied",
        })
        authed_at.run()

    assert not authed_at.exception
    assert any(
        "invalid" in _val(el).lower() for el in authed_at.warning
    )


def _val(el) -> str:
    return el.value if hasattr(el, "value") else str(el)
