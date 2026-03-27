import streamlit as st
from src.services.api_client import verify_token, APIError


def render_login() -> None:
    """Render the Hugging Face login / token entry form."""
    st.header("Sign in with Hugging Face")
    st.markdown(
        "Enter a Hugging Face **write-access** token to authenticate. "
        "You can generate one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)."
    )

    with st.form("hf_login_form", clear_on_submit=False):
        token = st.text_input(
            "Access Token",
            type="password",
            placeholder="hf_...",
            help="Your Hugging Face token with write permissions.",
        )
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        if not token.strip():
            st.error("Please enter a Hugging Face access token.")
            return

        with st.spinner("Verifying token…"):
            try:
                result = verify_token(token.strip())
                st.session_state["hf_token"] = token.strip()
                st.session_state["hf_username"] = result["username"]
                st.success(f"Authenticated as **{result['username']}**")
                st.rerun()
            except APIError as exc:
                if exc.status_code == 401:
                    st.error("Invalid token. Please check your Hugging Face access token.")
                else:
                    st.error(f"Authentication failed: {exc.detail}")
            except Exception as exc:
                st.error(f"Could not reach the backend: {exc}")
