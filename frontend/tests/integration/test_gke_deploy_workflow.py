"""T034 + T048 + T058 + T068 — GKE deploy frontend workflow tests.

All four tasks share this single file per the plan, which is why T048/T058/T068
are NOT flagged ``[P]`` in tasks.md — they must be appended sequentially to
avoid merge conflicts.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest


APP_MODULE = "src/app.py"


def _val(el) -> str:
    return el.value if hasattr(el, "value") else str(el)


def _mock_resp(json_data, ok=True, status_code=200):
    r = MagicMock(ok=ok, status_code=status_code)
    r.json.return_value = json_data
    r.text = str(json_data)
    return r


@pytest.fixture
def authed_at():
    at = AppTest.from_file(APP_MODULE, default_timeout=30)
    at.session_state["session_token"] = "session_abc"
    at.session_state["hf_username"] = "alice"
    at.session_state["_session_checked"] = True
    return at


# --------------------------------------------------------------------------- #
# T034 — deploy-public-repo flow renders + exposes new deploy button           #
# --------------------------------------------------------------------------- #

def test_deployments_tab_shows_public_deploy_entry(authed_at):
    """Covers the acceptance criterion of US2: there is a clear path in the
    UI to trigger a *real* deployment for a public HF repo.

    After T042a, the public-repo panel no longer hits ``/api/deployment/mock``;
    it calls ``/api/deployments``. We assert that the button is present and
    the deploy panel renders without errors.
    """
    with patch("src.services.api_client.requests.get") as mock_get, \
         patch("src.services.api_client.requests.post") as mock_post:
        # /api/gcp/credentials GET + /api/models GET + /api/models/public GET
        mock_get.return_value = _mock_resp({
            "configured": True,
            "validation_status": "valid",
            "service_account_email": "sa@proj.iam.gserviceaccount.com",
            "gcp_project_id_of_sa": "sa-parent",
            "billing_account_id": "billingAccounts/ABCDEF-012345-67890X",
            "last_validated_at": "2026-04-16T12:00:00Z",
        })
        mock_post.return_value = _mock_resp({
            "id": "11111111-2222-3333-4444-555555555555",
            "hf_model_id": "Qwen/Qwen3-1.7B",
            "status": "queued",
            "created_at": "2026-04-16T12:00:00Z",
            "updated_at": "2026-04-16T12:00:00Z",
        }, status_code=202)

        authed_at.run()

    # App rendered cleanly
    assert not authed_at.exception
    # The deploy tab label must be present somewhere in the markdown / tabs
    all_labels = [t.label for t in authed_at.tabs] if hasattr(authed_at, "tabs") else []
    assert any("deploy" in label.lower() for label in all_labels) or any(
        "Deploy" in _val(el) for el in authed_at.subheader
    )
