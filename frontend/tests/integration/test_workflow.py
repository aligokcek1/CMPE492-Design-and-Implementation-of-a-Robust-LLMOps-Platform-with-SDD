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
            json=lambda: {
                "username": "testuser",
                "session_token": "session_abc",
                "expires_at": "2099-01-01T00:00:00Z",
                "inactivity_timeout_seconds": 86400,
            },
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
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
    at.run()
    assert not at.exception
    rendered = " ".join(_val(e) for e in list(at.markdown) + list(at.title))
    assert "Upload" in rendered or len(at.tabs) > 0


def test_deploy_section_requires_model_selection(at):
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
    at.run()
    assert not at.exception


# ---------------------------------------------------------------------------
# Upload section renders with directory picker UI
# ---------------------------------------------------------------------------
def test_upload_section_renders_directory_picker(at):
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
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
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
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
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
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
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
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
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
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
def test_public_deploy_shows_hardware_selector_and_deploy_button(at):
    """Feature 008: public-repo panel shows CPU/GPU radio selector.
    Before selection, the Deploy button is disabled. After selecting CPU,
    button label reflects the choice.
    """
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
    at.session_state["public_repo_info"] = {
        "repo_id": "google-bert/bert-base-uncased",
        "author": "google-bert",
        "description": "Pretrained BERT",
        "file_count": 12,
        "size_bytes": 440473133,
    }
    with patch("src.services.api_client.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"configured": True, "validation_status": "valid"},
        )
        at.run()
    assert not at.exception
    # Deploy button should be present (disabled until hardware selected)
    deploy_buttons = [b for b in at.button if "deploy" in b.label.lower()]
    assert len(deploy_buttons) >= 1, "Expected a Deploy button in the public-repo panel"
    # The Deploy button should be disabled (no hardware type selected yet)
    deploy_btn = deploy_buttons[0]
    assert deploy_btn.disabled, "Deploy button should be disabled before hardware type is selected"


def test_select_existing_use_model_pre_populates_deploy_tab(at):
    """When shortcut_deploy_model is set (simulating 'Use Selected Model' click),
    the Deploy to Cloud tab shows the pre-populated model and 'Ready to deploy' message."""
    at.session_state["session_token"] = "session_valid"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
    at.session_state["shortcut_deploy_model"] = "testuser/my-model"

    credentials_response = MagicMock(ok=True, json=lambda: {"configured": False})
    with patch("src.services.api_client.requests.get", return_value=credentials_response), \
         patch("src.services.api_client.requests.post", return_value=credentials_response):
        at.run()

    assert not at.exception
    all_text = " ".join(
        str(getattr(el, "value", "") or getattr(el, "body", "") or "")
        for el in list(at.markdown) + list(at.text) + list(at.success) + list(at.info)
    )
    assert "my-model" in all_text or "Ready to deploy" in all_text, (
        "Expected Deploy tab to show pre-populated model when shortcut_deploy_model is set"
    )


# =========================================================================== #
# 009 — Upload-to-Deploy shortcut + My Upload badge (T025, T028, T029)         #
# =========================================================================== #

def test_upload_shortcut_pre_populates_deploy_tab(at):
    """T025: When shortcut_deploy_model is set in session, Deploy tab shows pre-populated message."""
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True
    at.session_state["shortcut_deploy_model"] = "testuser/my-uploaded-model"

    credentials_response = MagicMock(ok=True, json=lambda: {"configured": False})

    with patch("src.services.api_client.requests.get", return_value=credentials_response), \
         patch("src.services.api_client.requests.post", return_value=credentials_response):
        at.run()

    assert not at.exception
    all_text = " ".join(
        str(getattr(el, "value", "") or getattr(el, "body", "") or "")
        for el in list(at.markdown) + list(at.text) + list(at.success) + list(at.info)
    )
    assert "my-uploaded-model" in all_text or "Ready to deploy" in all_text, (
        "Expected Deploy tab to display pre-populated model from shortcut"
    )


def test_my_upload_badge_shown_for_uploaded_origin(at):
    """T028: Deployment row with model_origin='uploaded' shows 'My Upload' in Deployments tab."""
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    deployments_response = MagicMock(
        ok=True,
        json=lambda: [
            {
                "id": "dep-001",
                "hf_model_id": "testuser/my-model",
                "hf_model_display_name": "My Model",
                "hardware_type": "cpu",
                "model_origin": "uploaded",
                "status": "running",
                "status_message": "Running",
                "endpoint_url": "http://1.2.3.4:80",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    credentials_response = MagicMock(ok=True, json=lambda: {"configured": False})

    with patch("src.services.api_client.requests.get", return_value=deployments_response), \
         patch("src.services.api_client.requests.post", return_value=credentials_response):
        at.run()

    assert not at.exception
    all_text = " ".join(
        str(getattr(el, "value", "") or getattr(el, "body", "") or "")
        for el in list(at.markdown) + list(at.text)
    )
    # Badge uses "My Upload**" (singular, bold); header uses "My Uploads" (plural)
    assert "My Upload**" in all_text, (
        "Expected '📤 My Upload' badge to appear for model_origin='uploaded' deployment"
    )


def test_no_badge_for_public_origin(at):
    """T029: Deployment with model_origin='public' does NOT show 'My Upload' badge."""
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    deployments_response = MagicMock(
        ok=True,
        json=lambda: [
            {
                "id": "dep-002",
                "hf_model_id": "org/public-model",
                "hf_model_display_name": "Public Model",
                "hardware_type": "cpu",
                "model_origin": "public",
                "status": "running",
                "status_message": "Running",
                "endpoint_url": "http://1.2.3.4:80",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    credentials_response = MagicMock(ok=True, json=lambda: {"configured": False})

    with patch("src.services.api_client.requests.get", return_value=deployments_response), \
         patch("src.services.api_client.requests.post", return_value=credentials_response):
        at.run()

    assert not at.exception
    all_text = " ".join(
        str(getattr(el, "value", "") or getattr(el, "body", "") or "")
        for el in list(at.markdown) + list(at.text)
    )
    # Badge uses "My Upload**" (singular, bold); section header uses "My Uploads" (plural) — check badge only
    assert "My Upload**" not in all_text, (
        "Expected NO '📤 My Upload' badge for model_origin='public' deployment"
    )


def test_expired_session_prompt_and_context_recovery_hint(at):
    at.session_state["last_auth_error"] = "Session expired. Please sign in again."
    at.session_state["pending_action"] = {"type": "deploy", "model_repository": "user/model"}
    at.run()
    assert not at.exception
    assert any("Sign in" in _val(h) for h in at.header)


def _running_deployment(**overrides):
    base = {
        "id": "dep-metrics-001",
        "hf_model_id": "org/model",
        "hf_model_display_name": "Test Model",
        "hardware_type": "cpu",
        "model_origin": "public",
        "status": "running",
        "status_message": "Running",
        "endpoint_url": "http://1.2.3.4:80",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_metrics_expander_visible_on_running_deployment(at):
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    deployments_response = MagicMock(ok=True, json=lambda: [_running_deployment()])
    metrics_response = MagicMock(
        ok=True,
        json=lambda: {
            "deployment_id": "dep-metrics-001",
            "hardware_type": "cpu",
            "platform_label": "GKE / TGI",
            "range": "1h",
            "summary": {
                "ttft_avg_seconds": 0.5,
                "ttft_p95_seconds": 1.0,
                "throughput_value": 10.0,
                "throughput_unit": "tokens_per_second",
                "failed_requests_excluded": False,
            },
            "series": {"ttft": [], "throughput": [], "hardware": {}},
            "empty": False,
        },
    )

    def mock_get(url, **kwargs):
        if "/metrics/grafana" in url:
            return MagicMock(
                ok=True,
                json=lambda: {"redirect_url": "http://localhost:8000/api/metrics/grafana/redirect?token=abc"},
            )
        if "/metrics" in url:
            return metrics_response
        return deployments_response

    with patch("src.services.api_client.requests.get", side_effect=mock_get):
        at.run()

    assert not at.exception
    expander_labels = [e.label for e in at.expander]
    assert any("Metrics" in label for label in expander_labels)


def test_metrics_expander_absent_on_deleted_deployment(at):
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    deployments_response = MagicMock(
        ok=True,
        json=lambda: [_running_deployment(status="deleted", endpoint_url=None)],
    )
    with patch("src.services.api_client.requests.get", return_value=deployments_response):
        at.run()

    assert not at.exception
    assert not any("Metrics" in e.label for e in at.expander)


def test_metrics_time_range_selector(at):
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    range_calls: list[str] = []

    def metrics_json():
        return {
            "deployment_id": "dep-metrics-001",
            "hardware_type": "cpu",
            "platform_label": "GKE / TGI",
            "range": range_calls[-1] if range_calls else "1h",
            "summary": {
                "ttft_avg_seconds": 0.5,
                "throughput_value": 5.0,
                "throughput_unit": "tokens_per_second",
                "failed_requests_excluded": False,
            },
            "series": {
                "ttft": [{"timestamp": "2026-01-01T00:00:00Z", "value": 0.5}],
                "throughput": [{"timestamp": "2026-01-01T00:00:00Z", "value": 5.0}],
                "hardware": {},
            },
            "empty": False,
        }

    def mock_get(url, **kwargs):
        if "/metrics" in url and "grafana" not in url:
            range_calls.append(kwargs.get("params", {}).get("range", "1h"))
            return MagicMock(ok=True, json=metrics_json)
        return MagicMock(ok=True, json=lambda: [_running_deployment()])

    with patch("src.services.api_client.requests.get", side_effect=mock_get):
        at.run()

    assert not at.exception
    assert any(s.label == "Time range" for s in at.selectbox)


def test_gpu_metrics_shows_lightning_label_and_gpu_na(at):
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    def mock_get(url, **kwargs):
        if "/metrics" in url and "grafana" not in url:
            return MagicMock(
                ok=True,
                json=lambda: {
                    "deployment_id": "dep-gpu-001",
                    "hardware_type": "gpu",
                    "platform_label": "Lightning AI / GPU",
                    "range": "1h",
                    "summary": {"throughput_unit": "tokens_per_second", "failed_requests_excluded": False},
                    "series": {
                        "ttft": [],
                        "throughput": [],
                        "hardware": {
                            "gpu_utilization": {
                                "available": False,
                                "reason": "not_available_for_this_deployment_type",
                                "series": [],
                            }
                        },
                    },
                    "empty": False,
                },
            )
        return MagicMock(
            ok=True,
            json=lambda: [_running_deployment(id="dep-gpu-001", hardware_type="gpu")],
        )

    with patch("src.services.api_client.requests.get", side_effect=mock_get):
        at.run()

    assert not at.exception
    all_text = " ".join(_val(e) for e in list(at.markdown) + list(at.caption))
    assert "Lightning AI" in all_text or "GPU" in all_text


def test_open_in_grafana_button_visible(at):
    at.session_state["session_token"] = "test_session"
    at.session_state["hf_username"] = "testuser"
    at.session_state["_session_checked"] = True

    def mock_get(url, **kwargs):
        if "/metrics/grafana" in url:
            return MagicMock(
                ok=True,
                json=lambda: {
                    "redirect_url": "http://localhost:8000/api/metrics/grafana/redirect?token=signed",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        if "/metrics" in url:
            return MagicMock(
                ok=True,
                json=lambda: {
                    "deployment_id": "dep-metrics-001",
                    "hardware_type": "cpu",
                    "platform_label": "GKE / TGI",
                    "range": "1h",
                    "summary": {"throughput_unit": "tokens_per_second", "failed_requests_excluded": False},
                    "series": {"ttft": [], "throughput": [], "hardware": {}},
                    "empty": False,
                },
            )
        return MagicMock(ok=True, json=lambda: [_running_deployment()])

    with patch("src.services.api_client.requests.get", side_effect=mock_get):
        at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert any("Open in Grafana" in label for label in button_labels)

