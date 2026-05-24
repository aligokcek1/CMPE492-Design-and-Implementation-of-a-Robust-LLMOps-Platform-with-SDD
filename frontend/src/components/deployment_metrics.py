"""Native Streamlit metrics panel for running deployments (feature 010)."""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.services.api_client import APIError, get_deployment_metrics, get_grafana_link
from src.services.session_client import get_session_token


def _series_to_df(points: list[dict[str, Any]]) -> pd.DataFrame | None:
    if not points:
        return None
    df = pd.DataFrame(points)
    if df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df[["value"]]


def render_deployment_metrics_panel(deployment_id: str, hardware_type: str) -> None:
    """Metrics expander for a single running deployment."""
    platform = "GKE / TGI" if hardware_type == "cpu" else "Lightning AI / GPU"
    with st.expander("📈 Metrics", expanded=False):
        range_options = {"Last hour": "1h", "Last 24 hours": "24h", "Last 7 days": "7d"}
        selected_label = st.selectbox(
            "Time range",
            options=list(range_options.keys()),
            key=f"metrics_range_{deployment_id}",
        )
        metrics_range = range_options[selected_label]

        token = get_session_token()
        if not token:
            st.warning("Sign in to view metrics.")
            return

        try:
            data = get_deployment_metrics(token, deployment_id, metrics_range)
        except APIError as exc:
            if exc.status_code == 503:
                st.error(exc.detail or "Metrics temporarily unavailable.")
            else:
                st.error(f"Could not load metrics: {exc.detail}")
            return

        if data.get("error"):
            st.warning(data["error"])

        if data.get("empty"):
            st.info("No inference traffic recorded in this time range yet.")
            return

        summary = data.get("summary") or {}
        col1, col2 = st.columns(2)
        with col1:
            ttft_avg = summary.get("ttft_avg_seconds")
            st.metric("Avg TTFT (s)", f"{ttft_avg:.2f}" if ttft_avg is not None else "—")
            ttft_p95 = summary.get("ttft_p95_seconds")
            if ttft_p95 is not None:
                st.caption(f"p95 TTFT: {ttft_p95:.2f}s")
        with col2:
            throughput = summary.get("throughput_value")
            unit = summary.get("throughput_unit", "tokens_per_second")
            unit_label = "tok/s" if unit == "tokens_per_second" else "req/s"
            st.metric("Throughput", f"{throughput:.2f} {unit_label}" if throughput is not None else "—")

        if summary.get("failed_requests_excluded"):
            st.caption("Failed requests are excluded from TTFT and throughput calculations.")

        st.caption(f"Platform: {data.get('platform_label', platform)}")

        series = data.get("series") or {}
        ttft_df = _series_to_df(series.get("ttft") or [])
        if ttft_df is not None:
            st.markdown("**TTFT trend**")
            st.line_chart(ttft_df)

        throughput_df = _series_to_df(series.get("throughput") or [])
        if throughput_df is not None:
            st.markdown("**Throughput trend**")
            st.line_chart(throughput_df)

        hardware = series.get("hardware") or {}
        _render_hardware_chart(hardware.get("cpu_utilization"), "CPU utilization", deployment_id, "cpu")
        _render_hardware_chart(hardware.get("memory_utilization"), "Memory utilization", deployment_id, "mem")
        _render_hardware_chart(hardware.get("gpu_utilization"), "GPU utilization", deployment_id, "gpu")

        if st.button("Open in Grafana", key=f"grafana_{deployment_id}"):
            try:
                link = get_grafana_link(token, deployment_id)
                st.markdown(
                    f'[Open Grafana dashboard]({link["redirect_url"]})',
                    unsafe_allow_html=True,
                )
            except APIError as exc:
                st.error(f"Could not open Grafana: {exc.detail}")


def _render_hardware_chart(
    hw_series: dict[str, Any] | None,
    title: str,
    deployment_id: str,
    suffix: str,
) -> None:
    if not hw_series:
        return
    if not hw_series.get("available"):
        reason = hw_series.get("reason") or "not available"
        st.markdown(f"**{title}**: N/A ({reason.replace('_', ' ')})")
        return
    df = _series_to_df(hw_series.get("series") or [])
    if df is not None:
        st.markdown(f"**{title}**")
        st.line_chart(df)


__all__ = ["render_deployment_metrics_panel"]
