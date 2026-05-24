"""File-based Prometheus scrape job provisioning."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("llmops.prometheus_provisioner")

_DEFAULT_SCRAPE_DIR = Path(__file__).resolve().parents[2] / "monitoring" / "scrape.d"


class PrometheusProvisioner(Protocol):
    async def provision_scrape_job(
        self,
        *,
        deployment_id: str,
        user_id: str,
        hardware_type: str,
        endpoint_url: str,
    ) -> str: ...

    async def decommission_scrape_job(self, *, scrape_job: str) -> None: ...


def _endpoint_host_port(endpoint_url: str) -> str:
    parsed = urlparse(endpoint_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


class FilePrometheusProvisioner:
    def __init__(
        self,
        *,
        scrape_dir: Path | None = None,
        reload_url: str | None = None,
    ) -> None:
        self._scrape_dir = scrape_dir or Path(
            os.environ.get("LLMOPS_PROMETHEUS_SCRAPE_DIR", str(_DEFAULT_SCRAPE_DIR))
        )
        self._reload_url = reload_url or os.environ.get("LLMOPS_PROMETHEUS_RELOAD_URL")

    def _job_name(self, deployment_id: str) -> str:
        return f"deployment-{deployment_id}"

    def _job_path(self, scrape_job: str) -> Path:
        return self._scrape_dir / f"{scrape_job}.yml"

    async def provision_scrape_job(
        self,
        *,
        deployment_id: str,
        user_id: str,
        hardware_type: str,
        endpoint_url: str,
    ) -> str:
        scrape_job = self._job_name(deployment_id)
        target = _endpoint_host_port(endpoint_url)
        content = (
            "scrape_configs:\n"
            f"  - job_name: {scrape_job}\n"
            "    metrics_path: /metrics\n"
            "    static_configs:\n"
            f"      - targets: ['{target}']\n"
            "        labels:\n"
            f"          deployment_id: '{deployment_id}'\n"
            f"          user_id: '{user_id}'\n"
            f"          hardware_type: '{hardware_type}'\n"
        )
        self._scrape_dir.mkdir(parents=True, exist_ok=True)
        self._job_path(scrape_job).write_text(content, encoding="utf-8")
        await self._reload_if_configured()
        return scrape_job

    async def decommission_scrape_job(self, *, scrape_job: str) -> None:
        path = self._job_path(scrape_job)
        if path.exists():
            path.unlink()
        await self._reload_if_configured()

    async def _reload_if_configured(self) -> None:
        if not self._reload_url:
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self._reload_url)
        except Exception:  # noqa: BLE001
            logger.warning("Prometheus reload failed at %s", self._reload_url, exc_info=True)


__all__ = ["PrometheusProvisioner", "FilePrometheusProvisioner"]
