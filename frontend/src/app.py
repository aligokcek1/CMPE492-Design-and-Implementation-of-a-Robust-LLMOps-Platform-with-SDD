import sys
import os

# Ensure the frontend/ directory is on sys.path so `src.*` imports resolve
# regardless of whether the script is launched via `streamlit run src/app.py`
# (which puts frontend/src/ on the path) or via pytest (which puts frontend/ on it).
_frontend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _frontend_dir not in sys.path:
    sys.path.insert(0, _frontend_dir)

import streamlit as st  # noqa: E402

from src.components.auth import render_login  # noqa: E402
from src.components.upload import render_upload_section, render_model_selector  # noqa: E402
from src.components.deploy import render_deployment_section, render_public_repo_deploy_section  # noqa: E402
from src.components.gcp_credentials import render_gcp_credentials_section  # noqa: E402
from src.services.api_client import APIError, get_session_status, logout  # noqa: E402
from src.services.session_client import (  # noqa: E402
    clear_session,
    get_persisted_session_token,
    get_session_token,
    set_session,
    sync_session_cookie,
)

st.set_page_config(
    page_title="LLMOps Platform",
    page_icon="🤗",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _is_authenticated() -> bool:
    return bool(get_session_token())


def _try_restore_session() -> None:
    if st.session_state.get("_session_checked"):
        return
    st.session_state["_session_checked"] = True
    token = get_session_token()
    if not token:
        token = get_persisted_session_token()
        if token:
            st.session_state["session_token"] = token
    if not token:
        return
    try:
        status = get_session_status(token)
        set_session(
            session_token=status["session_token"],
            username=status["username"],
            expires_at=status.get("expires_at"),
        )
    except APIError:
        clear_session()
    except Exception:
        clear_session()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("LLMOps Platform")
        st.markdown("---")
        if _is_authenticated():
            username = st.session_state.get("hf_username", "Unknown")
            st.success(f"Signed in as **{username}**")
            if st.button("Sign Out", use_container_width=True):
                token = get_session_token()
                if token:
                    try:
                        logout(token)
                    except Exception:
                        pass
                clear_session()
                st.rerun()
        else:
            st.info("Not authenticated.")

        st.markdown("---")
        st.caption("Robust Model Upload Flow · CMPE492")


def main() -> None:
    _try_restore_session()
    sync_session_cookie()
    render_sidebar()

    if not _is_authenticated():
        render_login()
        return

    if st.session_state.pop("reauth_completed", False):
        pending = st.session_state.pop("pending_action", None)
        if pending:
            st.success(
                "Re-authentication successful. You can continue: "
                f"`{pending.get('type', 'previous action')}`."
            )

    st.title("🤗 LLMOps Platform")
    st.markdown(
        "Welcome! Use the tabs below to **upload** a local model or **select** an existing one, "
        "then proceed to **deploy** it."
    )

    tab_upload, tab_select, tab_deploy, tab_gcp = st.tabs(
        ["📤 Upload Model", "🔍 Select Existing", "🚀 Deploy", "☁️ GCP Credentials"]
    )

    with tab_upload:
        try:
            render_upload_section()
        except Exception as exc:
            st.error(f"An unexpected error occurred in the upload section: {exc}")

    with tab_select:
        try:
            render_model_selector()
        except Exception as exc:
            st.error(f"An unexpected error occurred in the model selection section: {exc}")

    with tab_deploy:
        try:
            render_deployment_section()
        except Exception as exc:
            st.error(f"An unexpected error occurred in the deployment section: {exc}")

        st.divider()

        try:
            render_public_repo_deploy_section()
        except Exception as exc:
            st.error(f"An unexpected error occurred in the public deploy section: {exc}")

    with tab_gcp:
        try:
            render_gcp_credentials_section()
        except Exception as exc:
            st.error(f"An unexpected error occurred in the GCP credentials section: {exc}")


if __name__ == "__main__":
    main()
