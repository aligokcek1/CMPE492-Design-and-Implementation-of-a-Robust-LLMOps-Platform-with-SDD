import posixpath

import streamlit as st
from src.services.api_client import start_upload, list_models, APIError

MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GB


def _strip_top_dir(name: str) -> str:
    """Strip the top-level directory from a webkitRelativePath-style name.

    Browser directory uploads produce paths like ``selected-dir/sub/file.ext``.
    The first component is the directory the user picked, which is redundant
    because the target HF repo is specified separately.  Strip it so only the
    internal structure is preserved.  If the path has no directory component
    (plain filename), return it unchanged.
    """
    parts = posixpath.normpath(name).split("/")
    if len(parts) > 1:
        return "/".join(parts[1:])
    return name


def _render_upload_results() -> None:
    """Display persisted per-folder upload results from session state."""
    result = st.session_state.get("upload_result")
    if not result:
        return
    folder_results = result.get("folder_results", [])
    if not folder_results:
        return
    st.markdown("### Upload Results")
    successes = sum(1 for r in folder_results if r["status"] == "success")
    total = len(folder_results)
    st.progress(successes / total if total else 1.0)
    for r in folder_results:
        if r["status"] == "success":
            st.markdown(f"✅ **{r['folder_name']}** — uploaded successfully")
        else:
            st.markdown(f"❌ **{r['folder_name']}** — {r.get('error', 'unknown error')}")


def render_upload_section() -> None:
    """Render the model upload UI with native directory and file pickers."""
    st.subheader("Upload a Local Model")
    st.markdown(
        "Pick a model folder from your computer, or select individual files. "
        "The directory structure is preserved inside the target Hugging Face repository."
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

    dir_key_idx = st.session_state.get("_dir_key_idx", 0)
    files_key_idx = st.session_state.get("_files_key_idx", 0)

    dir_files = st.file_uploader(
        "Upload a model directory",
        accept_multiple_files="directory",
        help="Select a folder — all files and sub-folders will be uploaded.",
        key=f"upload_dir_{dir_key_idx}",
    )
    if dir_files and st.button("Clear directory", key="btn_clear_dir"):
        st.session_state["_dir_key_idx"] = dir_key_idx + 1
        st.rerun()

    individual_files = st.file_uploader(
        "Or upload individual files",
        accept_multiple_files=True,
        help="Select one or more loose files to place at the repository root.",
        key=f"upload_files_{files_key_idx}",
    )
    if individual_files and st.button("Clear files", key="btn_clear_files"):
        st.session_state["_files_key_idx"] = files_key_idx + 1
        st.rerun()

    all_files: list[tuple[str, object]] = []
    if dir_files:
        for f in dir_files:
            all_files.append((_strip_top_dir(f.name), f))
    if individual_files:
        for f in individual_files:
            all_files.append((f.name, f))

    has_files = len(all_files) > 0

    if st.button(
        "Upload to Hugging Face",
        key="btn_upload",
        use_container_width=True,
        disabled=not has_files,
    ):
        if not repo_name or "/" not in repo_name or repo_name.endswith("/"):
            st.error("Please provide a valid repository ID (e.g. username/my-model).")
            return

        total_bytes = sum(f.size for _, f in all_files)
        if total_bytes > MAX_UPLOAD_BYTES:
            st.error(
                "Total upload size exceeds the platform limit "
                f"({MAX_UPLOAD_BYTES / (1024**3):.0f} GB). "
                "Please reduce the number or size of files."
            )
            return

        with st.spinner("Uploading…"):
            try:
                result = start_upload(token, repo_name, all_files)
                st.session_state["selected_model"] = repo_name
                st.session_state["upload_result"] = result
                st.toast(f"Model uploaded! Session: {result['session_id']}", icon="✅")
                st.success(
                    f"Successfully uploaded to **{repo_name}**. "
                    f"Session ID: `{result['session_id']}`"
                )
            except APIError as exc:
                st.session_state.pop("upload_result", None)
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
                elif exc.status_code == 413:
                    st.error("Total upload size exceeds the platform limit.")
                else:
                    st.error(f"Upload failed: {exc.detail}")
            except Exception as exc:
                st.session_state.pop("upload_result", None)
                st.error(f"Unexpected error during upload: {exc}")

    _render_upload_results()


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
