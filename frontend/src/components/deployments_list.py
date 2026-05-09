"""Feature 007 / US3 + US4 + US5 — deployments list with delete, dismiss, and inference panel."""
from __future__ import annotations

from typing import Any

import streamlit as st

from src.services.api_client import (
    APIError,
    delete_deployment,
    dismiss_deployment,
    list_deployments,
    run_inference,
)
from src.services.session_client import get_session_token


_STATUS_BADGES = {
    "queued": ("🟡", "Queued"),
    "deploying": ("🔵", "Deploying"),
    "running": ("🟢", "Running"),
    "failed": ("🔴", "Failed"),
    "deleting": ("🟠", "Deleting"),
    "deleted": ("⚪", "Deleted"),
    "lost": ("👻", "Lost"),
}


def _format_status(status: str) -> str:
    icon, label = _STATUS_BADGES.get(status, ("❓", status))
    return f"{icon} **{label}**"


def _fetch_deployments() -> list[dict[str, Any]] | None:
    token = get_session_token()
    if not token:
        return None
    try:
        return list_deployments(token)
    except APIError as exc:
        st.error(f"Failed to load deployments: {exc.detail}")
        return None


def _render_inference_panel(deployment_id: str, endpoint_url: str | None) -> None:
    """Inline inference panel (US5) shown on running deployments."""
    if not endpoint_url:
        return

    with st.expander("💬 Run inference", expanded=False):
        with st.form(f"inference_form_{deployment_id}", clear_on_submit=False):
            prompt = st.text_area(
                "Prompt",
                height=120,
                key=f"prompt_{deployment_id}",
                placeholder="Write a short haiku about serverless inference.",
            )
            max_tokens = st.number_input(
                "Max tokens", min_value=1, max_value=4096, value=256, key=f"maxtok_{deployment_id}"
            )
            temperature = st.slider(
                "Temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1,
                key=f"temp_{deployment_id}",
            )
            submitted = st.form_submit_button("Send")

        if submitted:
            token = get_session_token()
            if not prompt.strip():
                st.warning("Prompt is empty.")
                return
            with st.spinner("Waiting for model (up to 120s)…"):
                try:
                    result = run_inference(
                        token,
                        deployment_id,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=int(max_tokens),
                        temperature=float(temperature),
                    )
                except APIError as exc:
                    if exc.status_code == 504:
                        st.error(
                            "Model did not respond within 120 seconds. "
                            "Click Send again to retry."
                        )
                    elif exc.status_code == 409:
                        st.error(f"Deployment is not running: {exc.detail}")
                    else:
                        st.error(f"Inference failed: {exc.detail}")
                    return
                except Exception as exc:
                    st.error(f"Unexpected error: {exc}")
                    return

            # OpenAI-style response passthrough
            choices = result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {}).get("content", "")
                st.success("Response:")
                st.markdown(msg)
            else:
                st.json(result)


def _render_single_deployment(dep: dict[str, Any]) -> None:
    dep_id = dep["id"]
    status = dep["status"]
    with st.container(border=True):
        cols = st.columns([3, 2, 3])
        with cols[0]:
            st.markdown(f"**{dep.get('hf_model_display_name') or dep['hf_model_id']}**")
            st.caption(f"`{dep['hf_model_id']}`")
        with cols[1]:
            st.markdown(_format_status(status))
            if dep.get("status_message"):
                st.caption(dep["status_message"])
        with cols[2]:
            if dep.get("endpoint_url"):
                st.markdown("**Endpoint**")
                st.code(dep["endpoint_url"], language=None)

        action_cols = st.columns([1, 1, 4])
        with action_cols[0]:
            if status == "lost":
                if st.button("🗑 Dismiss", key=f"dismiss_{dep_id}", use_container_width=True):
                    _handle_dismiss(dep_id)
            else:
                if st.button(
                    "Delete",
                    key=f"delete_{dep_id}",
                    use_container_width=True,
                    disabled=status in ("deleting", "deleted"),
                ):
                    st.session_state[f"_confirm_delete_{dep_id}"] = True
                    st.rerun()

        if st.session_state.get(f"_confirm_delete_{dep_id}"):
            st.warning(
                f"Really delete deployment `{dep_id[:8]}` and tear down its GCP project? "
                "This cannot be undone."
            )
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button("Yes, delete", key=f"delete_confirm_{dep_id}", use_container_width=True):
                    _handle_delete(dep_id)
            with c_no:
                if st.button("Cancel", key=f"delete_cancel_{dep_id}", use_container_width=True):
                    st.session_state.pop(f"_confirm_delete_{dep_id}", None)
                    st.rerun()

        if status == "running":
            _render_inference_panel(dep_id, dep.get("endpoint_url"))


def _handle_delete(dep_id: str) -> None:
    token = get_session_token()
    try:
        delete_deployment(token, dep_id)
        st.success(f"Deletion of `{dep_id[:8]}` queued.")
    except APIError as exc:
        if exc.status_code == 409 and exc.code == "credentials_invalid":
            st.error(
                "Your GCP credentials are invalid — update them before deleting. "
                "Running deployments are unaffected."
            )
        else:
            st.error(f"Delete failed: {exc.detail}")
    finally:
        st.session_state.pop(f"_confirm_delete_{dep_id}", None)
        st.rerun()


def _handle_dismiss(dep_id: str) -> None:
    token = get_session_token()
    try:
        dismiss_deployment(token, dep_id)
        st.success("Lost deployment dismissed.")
    except APIError as exc:
        st.error(f"Dismiss failed: {exc.detail}")
    st.rerun()


def render_deployments_list() -> None:
    st.subheader("Your deployments")
    deployments = _fetch_deployments()
    if deployments is None:
        return

    if not deployments:
        st.info(
            "You don't have any deployments yet. Go to the **🚀 Deploy** tab to "
            "create your first one from a public HuggingFace repo."
        )
        return

    for dep in deployments:
        _render_single_deployment(dep)

    st.caption(
        f"{len(deployments)} deployment{'s' if len(deployments) != 1 else ''}. "
        "List refreshes automatically when statuses change."
    )


__all__ = ["render_deployments_list"]
