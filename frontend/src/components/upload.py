import streamlit as st
from src.services.api_client import start_upload, list_models, APIError


def render_upload_section() -> None:
    """Render the local model upload UI."""
    st.subheader("Upload a Local Model")
    st.markdown(
        "Select a local directory containing your model files. "
        "All files in the directory will be uploaded to the specified Hugging Face repository."
    )

    token = st.session_state.get("hf_token", "")
    username = st.session_state.get("hf_username", "")

    repo_name = st.text_input(
        "Target Repository ID",
        value=f"{username}/",
        placeholder="username/my-model",
        help="Hugging Face repository ID in the format username/repo-name",
        key="upload_repo_id",
    )

    uploaded_files = st.file_uploader(
        "Upload model files",
        accept_multiple_files=True,
        help="Select all files from your model directory.",
        key="upload_files",
    )

    if st.button("Upload to Hugging Face", key="btn_upload", use_container_width=True):
        if not repo_name or "/" not in repo_name or repo_name.endswith("/"):
            st.error("Please provide a valid repository ID (e.g. username/my-model).")
            return
        if not uploaded_files:
            st.error("Please select at least one file to upload.")
            return

        progress_bar = st.progress(0, text="Uploading to Hugging Face…")

        try:
            result = start_upload(token, repo_name, uploaded_files)
            progress_bar.progress(100, text="Upload complete!")
            st.session_state["selected_model"] = repo_name
            st.toast(f"Model uploaded! Session: {result['session_id']}", icon="✅")
            st.success(
                f"Successfully uploaded to **{repo_name}**. "
                f"Session ID: `{result['session_id']}`"
            )

        except APIError as exc:
            progress_bar.empty()
            if exc.status_code == 403 or "write permission" in exc.detail.lower():
                st.error(
                    "Your Hugging Face token does not have **write permissions** for this repository. "
                    "Please generate a token with write access."
                )
            elif exc.status_code == 409:
                st.error(
                    f"Conflict: the repository **{repo_name}** already exists under a different user. "
                    "Please choose a different repository name."
                )
            else:
                st.error(f"Upload failed: {exc.detail}")
        except Exception as exc:
            progress_bar.empty()
            st.error(f"Unexpected error during upload: {exc}")


def render_model_selector() -> None:
    """Render the existing HF model selection UI."""
    st.subheader("Or Select an Existing Hugging Face Model")
    token = st.session_state.get("hf_token", "")

    if st.button("Refresh My Models", key="btn_refresh_models"):
        st.session_state.pop("hf_models_cache", None)

    if "hf_models_cache" not in st.session_state:
        with st.spinner("Fetching your models from Hugging Face…"):
            try:
                models = list_models(token)
                st.session_state["hf_models_cache"] = models
            except APIError as exc:
                st.error(f"Could not fetch models: {exc.detail}")
                return
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")
                return

    models = st.session_state.get("hf_models_cache", [])

    if not models:
        st.info("No models found in your Hugging Face account.")
        return

    model_ids = [m["id"] for m in models]
    selected = st.selectbox(
        "Select a model",
        options=model_ids,
        key="model_selector_dropdown",
    )

    if st.button("Use Selected Model", key="btn_use_model", use_container_width=True):
        st.session_state["selected_model"] = selected
        st.toast(f"Selected model: {selected}", icon="🤗")
        st.success(f"Using model: **{selected}**")
