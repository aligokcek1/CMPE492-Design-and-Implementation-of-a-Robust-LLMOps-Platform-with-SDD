"""Provision and decommission per-deployment monitoring resources."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from ..db.models import DeploymentRow
from .deployment_store import deployment_store
from .grafana_provisioner import GrafanaProvisioner, HttpGrafanaProvisioner
from .metrics_store import metrics_store
from .prometheus_provisioner import FilePrometheusProvisioner, PrometheusProvisioner

logger = logging.getLogger("llmops.monitoring_orchestrator")

_DECOMMISSION_RETENTION_DAYS = 7


def _metrics_disabled() -> bool:
    return os.environ.get("LLMOPS_METRICS_DISABLED") == "1"


class MonitoringOrchestrator:
    def __init__(
        self,
        *,
        prometheus: PrometheusProvisioner | None = None,
        grafana: GrafanaProvisioner | None = None,
    ) -> None:
        self._prometheus = prometheus or FilePrometheusProvisioner()
        self._grafana = grafana or HttpGrafanaProvisioner()

    async def provision_for_running_deployment(self, row: DeploymentRow) -> None:
        if _metrics_disabled():
            return
        if row.status != "running" or not row.endpoint_url:
            return
        existing = metrics_store.get_for_deployment(row.id)
        if existing is not None and existing.status == "active":
            return
        try:
            scrape_job = await self._prometheus.provision_scrape_job(
                deployment_id=row.id,
                user_id=row.user_id,
                hardware_type=row.hardware_type,
                endpoint_url=row.endpoint_url,
            )
            ds_uid, dash_uid = await self._grafana.provision_dashboard(
                deployment_id=row.id,
                user_id=row.user_id,
            )
            metrics_store.create_active(
                deployment_id=row.id,
                user_id=row.user_id,
                scrape_job=scrape_job,
                grafana_datasource_uid=ds_uid,
                grafana_dashboard_uid=dash_uid,
            )
            logger.info("Monitoring provisioned for deployment %s", row.id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to provision monitoring for deployment %s", row.id)

    async def schedule_decommission(self, deployment_id: str) -> None:
        if _metrics_disabled():
            return
        decommission_at = datetime.now(UTC) + timedelta(days=_DECOMMISSION_RETENTION_DAYS)
        metrics_store.mark_decommissioning(deployment_id=deployment_id, decommission_at=decommission_at)
        logger.info(
            "Monitoring decommission scheduled for %s at %s",
            deployment_id,
            decommission_at.isoformat(),
        )

    async def run_decommission_cycle(self) -> None:
        if _metrics_disabled():
            return
        now = datetime.now(UTC)
        due = metrics_store.list_due_for_decommission(now=now)
        for row in due:
            try:
                await self._prometheus.decommission_scrape_job(scrape_job=row.prometheus_scrape_job)
                await self._grafana.decommission(
                    datasource_uid=row.grafana_datasource_uid,
                    dashboard_uid=row.grafana_dashboard_uid,
                )
                metrics_store.delete(row.deployment_id)
                logger.info("Monitoring decommissioned for deployment %s", row.deployment_id)
            except Exception:  # noqa: BLE001
                logger.exception("Decommission failed for deployment %s", row.deployment_id)

    async def reconcile_on_startup(self) -> None:
        if _metrics_disabled():
            return
        rows = deployment_store.list_by_status("running")
        for row in rows:
            await self.provision_for_running_deployment(row)
        # Fix Grafana datasources that were provisioned with localhost Prometheus URL.
        for row in rows:
            monitoring = metrics_store.get_for_deployment(row.id)
            if monitoring is None or monitoring.status != "active":
                continue
            try:
                await self._grafana.ensure_datasource_reachable(
                    datasource_uid=monitoring.grafana_datasource_uid
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Could not reconcile Grafana datasource for %s",
                    row.id,
                    exc_info=True,
                )


monitoring_orchestrator = MonitoringOrchestrator()

__all__ = ["MonitoringOrchestrator", "monitoring_orchestrator"]
