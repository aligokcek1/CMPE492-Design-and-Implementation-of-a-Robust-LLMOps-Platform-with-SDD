"""Grafana datasource + dashboard provisioning via HTTP API."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Protocol

import httpx

logger = logging.getLogger("llmops.grafana_provisioner")

_DASHBOARD_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "monitoring"
    / "grafana"
    / "dashboards"
    / "deployment-metrics.json"
)


class GrafanaProvisioner(Protocol):
    async def provision_dashboard(
        self,
        *,
        deployment_id: str,
        user_id: str,
        datasource_uid: str,
    ) -> tuple[str, str]: ...

    async def decommission(self, *, datasource_uid: str, dashboard_uid: str) -> None: ...


class HttpGrafanaProvisioner:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        admin_user: str | None = None,
        admin_password: str | None = None,
        prometheus_url: str | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("LLMOPS_GRAFANA_URL", "http://localhost:3000")).rstrip("/")
        self._admin_user = admin_user or os.environ.get("LLMOPS_GRAFANA_ADMIN_USER", "admin")
        self._admin_password = admin_password or os.environ.get("LLMOPS_GRAFANA_ADMIN_PASSWORD", "admin")
        # URL stored in Grafana datasource config — must be reachable FROM the Grafana
        # container (Docker Compose service name), not from the host.
        self._prometheus_url = prometheus_url or os.environ.get(
            "LLMOPS_GRAFANA_PROMETHEUS_URL", "http://prometheus:9090"
        )

    def _auth(self) -> tuple[str, str]:
        return self._admin_user, self._admin_password

    def _datasource_uid(self, deployment_id: str) -> str:
        return f"dep-{deployment_id.replace('-', '')[:16]}"

    def _dashboard_uid(self, deployment_id: str) -> str:
        return f"dash-{deployment_id.replace('-', '')[:16]}"

    async def provision_dashboard(
        self,
        *,
        deployment_id: str,
        user_id: str,
        datasource_uid: str | None = None,
    ) -> tuple[str, str]:
        ds_uid = datasource_uid or self._datasource_uid(deployment_id)
        dash_uid = self._dashboard_uid(deployment_id)
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{self._base_url}/api/datasources",
                auth=self._auth(),
                json={
                    "name": f"LLMOps {deployment_id[:8]}",
                    "type": "prometheus",
                    "access": "proxy",
                    "url": self._prometheus_url,
                    "uid": ds_uid,
                    "isDefault": False,
                },
            )
            dashboard_body = json.loads(_DASHBOARD_TEMPLATE.read_text(encoding="utf-8"))
            dashboard_body["uid"] = dash_uid
            dashboard_body["title"] = f"LLMOps Deployment {deployment_id[:8]}"
            await client.post(
                f"{self._base_url}/api/dashboards/db",
                auth=self._auth(),
                json={
                    "dashboard": dashboard_body,
                    "overwrite": True,
                },
            )
        return ds_uid, dash_uid

    async def ensure_datasource_reachable(self, *, datasource_uid: str) -> None:
        """Update an existing datasource URL if it still points at localhost."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self._base_url}/api/datasources/uid/{datasource_uid}",
                auth=self._auth(),
            )
            if resp.status_code != 200:
                return
            ds = resp.json()
            if ds.get("url") == self._prometheus_url:
                return
            ds["url"] = self._prometheus_url
            await client.put(
                f"{self._base_url}/api/datasources/{ds['id']}",
                auth=self._auth(),
                json=ds,
            )

    async def decommission(self, *, datasource_uid: str, dashboard_uid: str) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                await client.delete(
                    f"{self._base_url}/api/dashboards/uid/{dashboard_uid}",
                    auth=self._auth(),
                )
            except Exception:  # noqa: BLE001
                logger.debug("Grafana dashboard delete failed for %s", dashboard_uid, exc_info=True)
            try:
                ds_list = await client.get(f"{self._base_url}/api/datasources/uid/{datasource_uid}", auth=self._auth())
                if ds_list.status_code == 200:
                    ds_id = ds_list.json().get("id")
                    if ds_id is not None:
                        await client.delete(
                            f"{self._base_url}/api/datasources/{ds_id}",
                            auth=self._auth(),
                        )
            except Exception:  # noqa: BLE001
                logger.debug("Grafana datasource delete failed for %s", datasource_uid, exc_info=True)


__all__ = ["GrafanaProvisioner", "HttpGrafanaProvisioner"]
