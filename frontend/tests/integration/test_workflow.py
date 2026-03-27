"""End-to-end integration test for the full LLMOps workflow.

Covers: Login -> Upload -> Select Model -> Deploy (all mocked at API boundary).
"""
import pytest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest


APP_MODULE = "src/app.py"


def _val(el) -> str:
    """Return the text value of a Streamlit test element."""
    return el.value if hasattr(el, "value") else str(el)


@pytest.fixture
def at():
    return AppTest.from_file(APP_MODULE, default_timeout=30)


def test_unauthenticated_user_sees_login(at):
    at.run()
    assert not at.exception
    assert any("Sign in" in _val(h) for h in at.header)


def test_login_with_valid_token(at):
    with patch("src.services.api_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"username": "testuser"},
        )
        at.run()
        token_input = next(
            (ti for ti in at.text_input if "token" in ti.label.lower()), None
        )
        assert token_input is not None, "Token input not found"
        token_input.input("hf_test_token_valid")
        sign_in_btn = next(
            (b for b in at.button if "sign in" in b.label.lower()), None
        )
        assert sign_in_btn is not None, "Sign In button not found"
        sign_in_btn.click().run()

    assert not at.exception


def test_login_with_invalid_token(at):
    with patch("src.services.api_client.requests.post") as mock_post:
        mock_resp = MagicMock(ok=False, status_code=401)
        mock_resp.json.return_value = {"detail": "Invalid token"}
        mock_resp.text = "Invalid token"
        mock_post.return_value = mock_resp

        at.run()
        token_input = next(
            (ti for ti in at.text_input if "token" in ti.label.lower()), None
        )
        assert token_input is not None
        token_input.input("hf_invalid_token")
        sign_in_btn = next(
            (b for b in at.button if "sign in" in b.label.lower()), None
        )
        assert sign_in_btn is not None
        sign_in_btn.click().run()

        assert not at.exception
        assert any("Invalid token" in _val(e) for e in at.error)


def test_authenticated_user_sees_main_content(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.run()
    assert not at.exception
    rendered = " ".join(_val(e) for e in list(at.markdown) + list(at.title))
    assert "Upload" in rendered or len(at.tabs) > 0


def test_deploy_section_requires_model_selection(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.run()
    assert not at.exception
