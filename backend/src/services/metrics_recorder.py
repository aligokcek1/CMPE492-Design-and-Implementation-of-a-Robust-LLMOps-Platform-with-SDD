"""Prometheus metric instrumentation for inference proxy traffic."""
from __future__ import annotations

import os

from prometheus_client import Counter, Histogram


def _metrics_disabled() -> bool:
    return os.environ.get("LLMOPS_METRICS_DISABLED") == "1"


_LABELS = ("deployment_id", "user_id", "hardware_type")
_OUTCOME_LABELS = ("deployment_id", "user_id", "hardware_type", "outcome")

TTFT_SECONDS = Histogram(
    "llmops_ttft_seconds",
    "Time to first response byte for inference requests",
    _LABELS,
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

TOKENS_TOTAL = Counter(
    "llmops_tokens_total",
    "Total output tokens counted from inference responses",
    _LABELS,
)

INFERENCE_REQUESTS_TOTAL = Counter(
    "llmops_inference_requests_total",
    "Inference request outcomes",
    _OUTCOME_LABELS,
)


def record_success(
    *,
    deployment_id: str,
    user_id: str,
    hardware_type: str,
    ttft_seconds: float,
    token_count: int,
) -> None:
    if _metrics_disabled():
        return
    if token_count <= 0:
        record_outcome(
            deployment_id=deployment_id,
            user_id=user_id,
            hardware_type=hardware_type,
            outcome="no_token",
        )
        return
    TTFT_SECONDS.labels(
        deployment_id=deployment_id,
        user_id=user_id,
        hardware_type=hardware_type,
    ).observe(ttft_seconds)
    TOKENS_TOTAL.labels(
        deployment_id=deployment_id,
        user_id=user_id,
        hardware_type=hardware_type,
    ).inc(token_count)
    record_outcome(
        deployment_id=deployment_id,
        user_id=user_id,
        hardware_type=hardware_type,
        outcome="success",
    )


def record_outcome(
    *,
    deployment_id: str,
    user_id: str,
    hardware_type: str,
    outcome: str,
) -> None:
    if _metrics_disabled():
        return
    INFERENCE_REQUESTS_TOTAL.labels(
        deployment_id=deployment_id,
        user_id=user_id,
        hardware_type=hardware_type,
        outcome=outcome,
    ).inc()


__all__ = [
    "TTFT_SECONDS",
    "TOKENS_TOTAL",
    "INFERENCE_REQUESTS_TOTAL",
    "record_success",
    "record_outcome",
]
