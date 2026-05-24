from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MetricsRange(str, Enum):
    one_hour = "1h"
    twenty_four_hours = "24h"
    seven_days = "7d"


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float


class HardwareSeries(BaseModel):
    available: bool
    reason: str | None = None
    series: list[MetricPoint] = Field(default_factory=list)


class MetricsSummary(BaseModel):
    ttft_avg_seconds: float | None = None
    ttft_p95_seconds: float | None = None
    throughput_value: float | None = None
    throughput_unit: Literal["tokens_per_second", "requests_per_second"] = "tokens_per_second"
    failed_requests_excluded: bool = True


class MetricsSeriesBundle(BaseModel):
    ttft: list[MetricPoint] = Field(default_factory=list)
    throughput: list[MetricPoint] = Field(default_factory=list)
    hardware: dict[str, HardwareSeries] = Field(
        default_factory=lambda: {
            "cpu_utilization": HardwareSeries(available=False),
            "memory_utilization": HardwareSeries(available=False),
            "gpu_utilization": HardwareSeries(available=False),
        }
    )


class DeploymentMetricsResponse(BaseModel):
    deployment_id: str
    hardware_type: Literal["cpu", "gpu"]
    platform_label: str
    range: MetricsRange
    summary: MetricsSummary
    series: MetricsSeriesBundle
    empty: bool
    error: str | None = None


class GrafanaLinkResponse(BaseModel):
    redirect_url: str
    expires_at: datetime


__all__ = [
    "MetricsRange",
    "MetricPoint",
    "HardwareSeries",
    "MetricsSummary",
    "MetricsSeriesBundle",
    "DeploymentMetricsResponse",
    "GrafanaLinkResponse",
]
