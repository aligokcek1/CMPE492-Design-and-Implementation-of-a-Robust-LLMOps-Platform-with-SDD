import sys
import os

# Ensure the frontend/ directory is on sys.path so `src.*` imports resolve
# regardless of whether the script is launched via `streamlit run src/app.py`
# (which puts frontend/src/ on the path) or via pytest (which puts frontend/ on it).
_frontend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _frontend_dir not in sys.path:
    sys.path.insert(0, _frontend_dir)

import streamlit as st

from src.components.auth import render_login
from src.components.upload import render_upload_section, render_model_selector
from src.components.deploy import render_deployment_section, render_public_repo_deploy_section

st.set_page_config(
    page_title="LLMOps Platform",
    page_icon="🤗",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _is_authenticated() -> bool:
    return bool(st.session_state.get("hf_token"))


def render_sidebar() -> None:
    with st.sidebar:
        st.title("LLMOps Platform")
        st.markdown("---")
        if _is_authenticated():
            username = st.session_state.get("hf_username", "Unknown")
            st.success(f"Signed in as **{username}**")
            if st.button("Sign Out", use_container_width=True):
                for key in ["hf_token", "hf_username", "selected_model", "hf_models_cache", "deployment_result"]:
                    st.session_state.pop(key, None)
                st.rerun()
        else:
            st.info("Not authenticated.")

        st.markdown("---")
        st.caption("Robust Model Upload Flow · CMPE492")


def main() -> None:
    render_sidebar()

    if not _is_authenticated():
        render_login()
        return

    st.title("🤗 LLMOps Platform")
    st.markdown(
        "Welcome! Use the tabs below to **upload** a local model or **select** an existing one, "
        "then proceed to **deploy** it."
    )

    tab_upload, tab_select, tab_deploy = st.tabs(
        ["📤 Upload Model", "🔍 Select Existing", "🚀 Deploy"]
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


if __name__ == "__main__":
    main()
