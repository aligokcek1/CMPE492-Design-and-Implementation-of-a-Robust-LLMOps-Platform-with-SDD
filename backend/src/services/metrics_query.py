"""Prometheus query client with server-side label injection."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from ..models.metrics import (
    DeploymentMetricsResponse,
    HardwareSeries,
    MetricPoint,
    MetricsRange,
    MetricsSeriesBundle,
    MetricsSummary,
)

logger = logging.getLogger("llmops.metrics_query")

_RANGE_SECONDS = {
    MetricsRange.one_hour: 3600,
    MetricsRange.twenty_four_hours: 86400,
    MetricsRange.seven_days: 604800,
}

_GPU_NA_REASON = "not_available_for_this_deployment_type"


class MetricsQueryClient(Protocol):
    async def query(self, promql: str) -> dict: ...

    async def query_range(self, promql: str, *, start: datetime, end: datetime, step: str) -> dict: ...


class HttpMetricsQueryClient:
    def __init__(self, *, base_url: str | None = None) -> None:
        self._base_url = (base_url or os.environ.get("LLMOPS_PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")

    async def query(self, promql: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/query",
                params={"query": promql},
            )
            resp.raise_for_status()
            return resp.json()

    async def query_range(self, promql: str, *, start: datetime, end: datetime, step: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/query_range",
                params={
                    "query": promql,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": step,
                },
            )
            resp.raise_for_status()
            return resp.json()


class FakeMetricsQueryClient:
    """Deterministic Prometheus responses for contract tests."""

    def __init__(self) -> None:
        self.unreachable = False
        self.empty = False
        self.gpu_series_available = False
        self._responses: dict[str, dict] = {}

    def set_unreachable(self, value: bool = True) -> None:
        self.unreachable = value

    def set_empty(self, value: bool = True) -> None:
        self.empty = value

    async def query(self, promql: str) -> dict:
        if self.unreachable:
            raise httpx.ConnectError("Prometheus unreachable")
        if promql in self._responses:
            return self._responses[promql]
        if self.empty:
            return {"status": "success", "data": {"resultType": "vector", "result": []}}
        if "llmops_ttft_seconds" in promql and "quantile" in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "1.25"]}]},
            }
        if "llmops_ttft_seconds" in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "0.85"]}]},
            }
        if "llmops_tokens_total" in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "12.5"]}]},
            }
        if "llmops_inference_requests_total" in promql and 'outcome="error"' in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "2"]}]},
            }
        if "process_cpu_seconds_total" in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "0.42"]}]},
            }
        if "process_resident_memory_bytes" in promql:
            return {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"value": [0, "536870912"]}]},
            }
        if "gpu_utilization" in promql:
            if self.gpu_series_available:
                return {
                    "status": "success",
                    "data": {"resultType": "vector", "result": [{"value": [0, "0.75"]}]},
                }
            return {"status": "success", "data": {"resultType": "vector", "result": []}}
        return {"status": "success", "data": {"resultType": "vector", "result": []}}

    async def query_range(self, promql: str, *, start: datetime, end: datetime, step: str) -> dict:
        if self.unreachable:
            raise httpx.ConnectError("Prometheus unreachable")
        if self.empty:
            return {"status": "success", "data": {"resultType": "matrix", "result": []}}
        now = int(end.timestamp())
        start_ts = int(start.timestamp())
        points = [
            [start_ts + 60, "0.5"],
            [start_ts + 120, "0.7"],
            [now, "0.9"],
        ]
        if "24h" in promql or (end - start).total_seconds() >= 86400:
            points = [[start_ts + i * 3600, str(0.5 + i * 0.1)] for i in range(3)]
        if "7d" in promql or (end - start).total_seconds() >= 604800:
            points = [[start_ts + i * 86400, str(0.4 + i * 0.05)] for i in range(3)]
        return {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [{"values": points}],
            },
        }


def _label_filter(deployment_id: str, user_id: str, **extra: str) -> str:
    parts = [f'deployment_id="{deployment_id}"', f'user_id="{user_id}"']
    for key, val in extra.items():
        parts.append(f'{key}="{val}"')
    return "{" + ",".join(parts) + "}"


def _scalar_from_vector(data: dict) -> float | None:
    results = data.get("data", {}).get("result", [])
    if not results:
        return None
    try:
        return float(results[0]["value"][1])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def _series_from_matrix(data: dict) -> list[MetricPoint]:
    results = data.get("data", {}).get("result", [])
    if not results:
        return []
    values = results[0].get("values", [])
    points: list[MetricPoint] = []
    for ts, val in values:
        try:
            points.append(
                MetricPoint(
                    timestamp=datetime.fromtimestamp(float(ts), tz=UTC),
                    value=float(val),
                )
            )
        except (TypeError, ValueError):
            continue
    return points


class MetricsQueryService:
    def __init__(self, client: MetricsQueryClient | None = None) -> None:
        self._client = client or HttpMetricsQueryClient()

    async def fetch_deployment_metrics(
        self,
        *,
        deployment_id: str,
        user_id: str,
        hardware_type: str,
        range: MetricsRange,
    ) -> DeploymentMetricsResponse:
        labels = _label_filter(deployment_id, user_id)
        platform_label = "GKE / TGI" if hardware_type == "cpu" else "Lightning AI / GPU"
        end = datetime.now(UTC)
        start = end - timedelta(seconds=_RANGE_SECONDS[range])
        step = "60s" if range == MetricsRange.one_hour else ("300s" if range == MetricsRange.twenty_four_hours else "3600s")

        try:
            avg_ttft_data = await self._client.query(
                f"avg(rate(llmops_ttft_seconds_sum{labels}[5m]) / "
                f"rate(llmops_ttft_seconds_count{labels}[5m]))"
            )
            p95_ttft_data = await self._client.query(
                f"histogram_quantile(0.95, sum(rate(llmops_ttft_seconds_bucket{labels}[5m])) by (le))"
            )
            tokens_rate_data = await self._client.query(
                f"sum(rate(llmops_tokens_total{labels}[5m]))"
            )
            error_count_data = await self._client.query(
                f'sum(increase(llmops_inference_requests_total'
                f'{_label_filter(deployment_id, user_id, outcome="error")}[5m]))'
            )

            ttft_series_data = await self._client.query_range(
                f"histogram_quantile(0.50, sum(rate(llmops_ttft_seconds_bucket{labels}[5m])) by (le))",
                start=start,
                end=end,
                step=step,
            )
            throughput_series_data = await self._client.query_range(
                f"sum(rate(llmops_tokens_total{labels}[5m]))",
                start=start,
                end=end,
                step=step,
            )

            cpu_data = await self._client.query(
                f"rate(process_cpu_seconds_total{labels}[5m])"
            )
            mem_data = await self._client.query(
                f"process_resident_memory_bytes{labels}"
            )
            gpu_data = await self._client.query(f"gpu_utilization{labels}")
            cpu_series_data = await self._client.query_range(
                f"rate(process_cpu_seconds_total{labels}[5m])",
                start=start,
                end=end,
                step=step,
            )
            mem_series_data = await self._client.query_range(
                f"process_resident_memory_bytes{labels}",
                start=start,
                end=end,
                step=step,
            )
            gpu_series_data = await self._client.query_range(
                f"gpu_utilization{labels}",
                start=start,
                end=end,
                step=step,
            )
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            logger.warning("Prometheus query failed for %s: %s", deployment_id, exc)
            return DeploymentMetricsResponse(
                deployment_id=deployment_id,
                hardware_type=hardware_type,  # type: ignore[arg-type]
                platform_label=platform_label,
                range=range,
                summary=MetricsSummary(failed_requests_excluded=True),
                series=MetricsSeriesBundle(),
                empty=True,
                error="Prometheus is unreachable — metrics temporarily unavailable.",
            )

        ttft_avg = _scalar_from_vector(avg_ttft_data)
        ttft_p95 = _scalar_from_vector(p95_ttft_data)
        tokens_rate = _scalar_from_vector(tokens_rate_data)
        error_count = _scalar_from_vector(error_count_data) or 0.0

        throughput_value = tokens_rate
        throughput_unit: str = "tokens_per_second"
        if throughput_value is None or throughput_value == 0:
            req_rate_data = await self._client.query(
                f'sum(rate(llmops_inference_requests_total'
                f'{_label_filter(deployment_id, user_id, outcome="success")}[5m]))'
            )
            throughput_value = _scalar_from_vector(req_rate_data)
            throughput_unit = "requests_per_second"

        ttft_series = _series_from_matrix(ttft_series_data)
        throughput_series = _series_from_matrix(throughput_series_data)

        cpu_scalar = _scalar_from_vector(cpu_data)
        mem_scalar = _scalar_from_vector(mem_data)
        gpu_scalar = _scalar_from_vector(gpu_data)

        cpu_available = hardware_type == "cpu" and cpu_scalar is not None
        mem_available = mem_scalar is not None
        gpu_available = hardware_type == "gpu" and gpu_scalar is not None

        hardware = {
            "cpu_utilization": HardwareSeries(
                available=cpu_available,
                reason=None if cpu_available else _GPU_NA_REASON if hardware_type == "gpu" else "no_data",
                series=_series_from_matrix(cpu_series_data) if cpu_available else [],
            ),
            "memory_utilization": HardwareSeries(
                available=mem_available,
                reason=None if mem_available else "no_data",
                series=_series_from_matrix(mem_series_data) if mem_available else [],
            ),
            "gpu_utilization": HardwareSeries(
                available=gpu_available,
                reason=None if gpu_available else _GPU_NA_REASON,
                series=_series_from_matrix(gpu_series_data) if gpu_available else [],
            ),
        }

        empty = (
            ttft_avg is None
            and ttft_p95 is None
            and throughput_value is None
            and not ttft_series
            and not throughput_series
        )

        return DeploymentMetricsResponse(
            deployment_id=deployment_id,
            hardware_type=hardware_type,  # type: ignore[arg-type]
            platform_label=platform_label,
            range=range,
            summary=MetricsSummary(
                ttft_avg_seconds=ttft_avg,
                ttft_p95_seconds=ttft_p95,
                throughput_value=throughput_value,
                throughput_unit=throughput_unit,  # type: ignore[arg-type]
                failed_requests_excluded=error_count > 0,
            ),
            series=MetricsSeriesBundle(
                ttft=ttft_series,
                throughput=throughput_series,
                hardware=hardware,
            ),
            empty=empty,
        )


__all__ = [
    "MetricsQueryClient",
    "HttpMetricsQueryClient",
    "FakeMetricsQueryClient",
    "MetricsQueryService",
]
