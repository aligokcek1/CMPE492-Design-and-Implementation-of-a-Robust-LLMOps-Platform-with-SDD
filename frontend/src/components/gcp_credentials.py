"""Streamlit component for the GCP credentials tab (feature 007 / US1)."""
from __future__ import annotations

import streamlit as st

from src.services.api_client import (
    APIError,
    delete_gcp_credentials,
    get_gcp_credentials_status,
    save_gcp_credentials,
)
from src.services.session_client import get_session_token


def _fetch_status() -> dict | None:
    token = get_session_token()
    if not token:
        return None
    try:
        return get_gcp_credentials_status(token)
    except APIError as exc:
        st.error(f"Failed to load credential status: {exc.detail}")
        return None


def _render_status_panel(status: dict) -> None:
    if not status.get("configured"):
        st.info("No GCP credentials configured yet. Save a service-account key + billing account to enable real model deployments.")
        return

    validation = status.get("validation_status") or "valid"
    if validation == "invalid":
        st.warning(
            "Your saved GCP credentials are currently **invalid** — probably "
            "revoked or permissions changed. New deployments and deletions "
            "are blocked until you submit a fresh key. "
            "Already-running deployments are unaffected."
        )
    else:
        st.success("GCP credentials are configured and **valid**.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Service account**")
        st.code(status.get("service_account_email") or "—", language=None)
        st.markdown("**SA's parent project**")
        st.code(status.get("gcp_project_id_of_sa") or "—", language=None)
    with cols[1]:
        st.markdown("**Billing account**")
        st.code(status.get("billing_account_id") or "—", language=None)
        st.markdown("**Last validated**")
        st.code(status.get("last_validated_at") or "—", language=None)

    if status.get("validation_error_message"):
        with st.expander("Validation error details"):
            st.code(status["validation_error_message"], language=None)


def _render_save_form() -> None:
    with st.form("gcp_credentials_form", clear_on_submit=False):
        st.markdown(
            "Paste the contents of a **service account key JSON** and a **billing account ID**. "
            "The key is encrypted at rest; the backend never returns it back."
        )
        sa_json = st.text_area(
            "Service account JSON",
            height=240,
            placeholder='{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}',
            key="gcp_sa_json_input",
        )
        billing_id = st.text_input(
            "Billing account ID",
            placeholder="billingAccounts/XXXXXX-XXXXXX-XXXXXX",
            key="gcp_billing_input",
        )
        submitted = st.form_submit_button("Save and validate", type="primary", use_container_width=True)

    if not submitted:
        return

    token = get_session_token()
    if not token:
        st.error("You must be signed in to save credentials.")
        return
    if not sa_json.strip() or not billing_id.strip():
        st.error("Both fields are required.")
        return

    try:
        new_status = save_gcp_credentials(token, sa_json, billing_id)
    except APIError as exc:
        st.error(f"Credential validation failed: {exc.detail}")
        return

    st.success("Credentials saved and validated.")
    st.session_state["gcp_credential_status"] = new_status
    st.rerun()


def render_gcp_credentials_section() -> None:
    st.subheader("GCP credentials")
    status = _fetch_status()
    if status is None:
        return

    _render_status_panel(status)
    st.divider()

    if status.get("configured"):
        cols = st.columns(2)
        with cols[0]:
            if st.button("Replace credentials", use_container_width=True):
                st.session_state["_gcp_show_form"] = True
        with cols[1]:
            if st.button("Delete credentials", type="secondary", use_container_width=True):
                token = get_session_token()
                try:
                    delete_gcp_credentials(token)
                    st.success("Credentials deleted.")
                    st.session_state.pop("_gcp_show_form", None)
                    st.rerun()
                except APIError as exc:
                    if exc.status_code == 409:
                        st.error(
                            "Cannot delete credentials while active deployments exist. "
                            "Delete those deployments first."
                        )
                    else:
                        st.error(f"Delete failed: {exc.detail}")

        if st.session_state.get("_gcp_show_form"):
            _render_save_form()
    else:
        _render_save_form()


__all__ = ["render_gcp_credentials_section"]
