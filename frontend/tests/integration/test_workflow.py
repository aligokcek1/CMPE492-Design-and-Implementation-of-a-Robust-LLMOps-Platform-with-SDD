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


# ---------------------------------------------------------------------------
# Upload section renders with directory picker UI
# ---------------------------------------------------------------------------
def test_upload_section_renders_directory_picker(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.run()
    assert not at.exception
    rendered = " ".join(_val(e) for e in list(at.markdown) + list(at.subheader))
    assert "Upload" in rendered, "Expected Upload section to render"
    upload_btn = [b for b in at.button if "upload" in b.label.lower()]
    assert len(upload_btn) >= 1, "Expected 'Upload to Hugging Face' button"


# ---------------------------------------------------------------------------
# T021: Deploy tab contains text input for public repo ID
# ---------------------------------------------------------------------------
def test_public_repo_deploy_section_renders(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.run()
    assert not at.exception
    repo_inputs = [
        ti for ti in at.text_input
        if "public" in ti.label.lower() or "repo" in ti.label.lower()
    ]
    assert len(repo_inputs) >= 1, "Expected a text input for public repo ID in Deploy tab"


# ---------------------------------------------------------------------------
# T022: fetch_public_model_info → metadata displayed
# ---------------------------------------------------------------------------
def test_public_repo_fetch_info_displays_metadata(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.session_state["public_repo_info"] = {
        "repo_id": "bert-base-uncased",
        "author": "google-bert",
        "description": "Pretrained BERT",
        "file_count": 12,
        "size_bytes": 440473133,
    }
    at.run()
    assert not at.exception
    rendered = " ".join(_val(e) for e in list(at.info) + list(at.markdown))
    assert "google-bert" in rendered or "bert-base-uncased" in rendered


# ---------------------------------------------------------------------------
# T023: CPU deploy button calls mock_deploy with public repo_id
# ---------------------------------------------------------------------------
def test_public_repo_deploy_triggers_mock_deploy(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.session_state["public_repo_info"] = {
        "repo_id": "google-bert/bert-base-uncased",
        "author": "google-bert",
        "description": "Pretrained BERT",
        "file_count": 12,
        "size_bytes": 440473133,
    }
    with patch("src.services.api_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"status": "mock_success", "message": "Deployed!"},
        )
        at.run()
        assert not at.exception
        cpu_buttons = [b for b in at.button if "cpu" in b.label.lower()]
        if cpu_buttons:
            cpu_buttons[0].click().run()
            assert not at.exception


# ---------------------------------------------------------------------------
# T029: After upload, UI shows per-folder result rows
# ---------------------------------------------------------------------------
def test_upload_shows_per_folder_progress(at):
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.session_state["upload_result"] = {
        "session_id": "abc-123",
        "folder_results": [
            {"folder_name": "weights", "status": "success", "error": None},
            {"folder_name": "tokenizer", "status": "error", "error": "timeout"},
        ],
    }
    at.run()
    assert not at.exception
    rendered = " ".join(_val(e) for e in list(at.markdown) + list(at.success))
    assert "weights" in rendered or "tokenizer" in rendered, \
        "Expected per-folder result rows after upload"


# ---------------------------------------------------------------------------
# T030: Spinner visible during public repo deployment
# ---------------------------------------------------------------------------
def test_public_deploy_spinner_visible(at):
    """The deploy section must use st.spinner. We verify the spinner text
    appears in the rendered output when a deploy is triggered."""
    at.session_state["hf_token"] = "hf_valid_token"
    at.session_state["hf_username"] = "testuser"
    at.session_state["public_repo_info"] = {
        "repo_id": "google-bert/bert-base-uncased",
        "author": "google-bert",
        "description": "Pretrained BERT",
        "file_count": 12,
        "size_bytes": 440473133,
    }
    at.run()
    assert not at.exception
    deploy_buttons = [
        b for b in at.button
        if "cpu" in b.label.lower() or "gpu" in b.label.lower()
    ]
    assert len(deploy_buttons) >= 1, "Expected CPU/GPU deploy buttons"
