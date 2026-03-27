import streamlit as st
from src.services.api_client import mock_deploy, APIError


def render_deployment_section() -> None:
    """Render the GCP deployment configuration and mock deployment UI."""
    st.subheader("Deploy to GCP (Simulated)")

    selected_model = st.session_state.get("selected_model", "")
    if not selected_model:
        st.warning("No model selected. Please upload or select a model first.")
        return

    st.markdown(f"**Model to deploy**: `{selected_model}`")

    col1, col2 = st.columns(2)
    with col1:
        cpu_selected = st.button(
            "🖥️ CPU",
            key="btn_cpu",
            use_container_width=True,
            help="Deploy on CPU infrastructure",
        )
    with col2:
        gpu_selected = st.button(
            "⚡ GPU",
            key="btn_gpu",
            use_container_width=True,
            help="Deploy on GPU infrastructure",
        )

    resource_type = None
    if cpu_selected:
        resource_type = "CPU"
    elif gpu_selected:
        resource_type = "GPU"

    if resource_type:
        token = st.session_state.get("hf_token", "")
        with st.spinner(f"Simulating {resource_type} deployment…"):
            try:
                result = mock_deploy(token, selected_model, resource_type)
                st.success(f"**{result['status'].upper()}**: {result['message']}")
                st.balloons()
                st.session_state["deployment_result"] = result
            except APIError as exc:
                st.error(f"Deployment failed: {exc.detail}")
            except Exception as exc:
                st.error(f"Unexpected error during deployment: {exc}")

    if "deployment_result" in st.session_state:
        with st.expander("Last Deployment Result", expanded=False):
            r = st.session_state["deployment_result"]
            st.json(r)
