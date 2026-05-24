"""DI helpers shared between FastAPI routes.

Kept in a separate module so route files can `Depends(get_gcp_provider)`
without pulling in `src.main` (which would be a circular import).
"""
from __future__ import annotations

import os

from ..services.gcp_fake_provider import FakeGCPProvider
from ..services.gcp_provider import GCPProvider
from ..services.grafana_fake_provisioner import FakeGrafanaProvisioner
from ..services.grafana_provisioner import GrafanaProvisioner, HttpGrafanaProvisioner
from ..services.lightning_ai_provider import LightningAIProvider, RealLightningAIProvider
from ..services.metrics_query import (
    FakeMetricsQueryClient,
    HttpMetricsQueryClient,
    MetricsQueryService,
)
from ..services.prometheus_fake_provisioner import FakePrometheusProvisioner
from ..services.prometheus_provisioner import FilePrometheusProvisioner, PrometheusProvisioner

_gcp_provider_instance: GCPProvider | None = None
_lightning_ai_provider_instance: LightningAIProvider | None = None
_prometheus_provisioner_instance: PrometheusProvisioner | None = None
_grafana_provisioner_instance: GrafanaProvisioner | None = None
_metrics_query_service_instance: MetricsQueryService | None = None


def _build_default_gcp_provider() -> GCPProvider:
    if os.environ.get("LLMOPS_USE_FAKE_GCP") == "1":
        return FakeGCPProvider()
    from ..services.gcp_real_provider import (
        RealGCPProvider,  # noqa: WPS433 - intentional lazy import
    )

    return RealGCPProvider()


def get_gcp_provider() -> GCPProvider:
    """FastAPI dependency returning the active GCPProvider.

    Tests override via ``app.dependency_overrides[get_gcp_provider] = ...``.
    """
    global _gcp_provider_instance
    if _gcp_provider_instance is None:
        _gcp_provider_instance = _build_default_gcp_provider()
    return _gcp_provider_instance


def reset_gcp_provider_for_tests() -> None:
    global _gcp_provider_instance
    _gcp_provider_instance = None


def get_lightning_ai_provider() -> LightningAIProvider:
    """FastAPI dependency returning the active LightningAIProvider.

    Tests override via ``app.dependency_overrides[get_lightning_ai_provider] = ...``.
    """
    global _lightning_ai_provider_instance
    if _lightning_ai_provider_instance is None:
        _lightning_ai_provider_instance = RealLightningAIProvider()
    return _lightning_ai_provider_instance


def reset_lightning_ai_provider_for_tests() -> None:
    global _lightning_ai_provider_instance
    _lightning_ai_provider_instance = None


def get_prometheus_provisioner() -> PrometheusProvisioner:
    global _prometheus_provisioner_instance
    if _prometheus_provisioner_instance is None:
        if os.environ.get("LLMOPS_USE_FAKE_PROMETHEUS") == "1":
            _prometheus_provisioner_instance = FakePrometheusProvisioner()
        else:
            _prometheus_provisioner_instance = FilePrometheusProvisioner()
    return _prometheus_provisioner_instance


def reset_prometheus_provisioner_for_tests() -> None:
    global _prometheus_provisioner_instance
    _prometheus_provisioner_instance = None


def get_grafana_provisioner() -> GrafanaProvisioner:
    global _grafana_provisioner_instance
    if _grafana_provisioner_instance is None:
        if os.environ.get("LLMOPS_USE_FAKE_GRAFANA") == "1":
            _grafana_provisioner_instance = FakeGrafanaProvisioner()
        else:
            _grafana_provisioner_instance = HttpGrafanaProvisioner()
    return _grafana_provisioner_instance


def reset_grafana_provisioner_for_tests() -> None:
    global _grafana_provisioner_instance
    _grafana_provisioner_instance = None


def get_metrics_query_service() -> MetricsQueryService:
    global _metrics_query_service_instance
    if _metrics_query_service_instance is None:
        if os.environ.get("LLMOPS_USE_FAKE_METRICS_QUERY") == "1":
            _metrics_query_service_instance = MetricsQueryService(client=FakeMetricsQueryClient())
        else:
            _metrics_query_service_instance = MetricsQueryService(client=HttpMetricsQueryClient())
    return _metrics_query_service_instance


def reset_metrics_query_service_for_tests() -> None:
    global _metrics_query_service_instance
    _metrics_query_service_instance = None


__all__ = [
    "get_gcp_provider",
    "reset_gcp_provider_for_tests",
    "get_lightning_ai_provider",
    "reset_lightning_ai_provider_for_tests",
    "get_prometheus_provisioner",
    "reset_prometheus_provisioner_for_tests",
    "get_grafana_provisioner",
    "reset_grafana_provisioner_for_tests",
    "get_metrics_query_service",
    "reset_metrics_query_service_for_tests",
]
