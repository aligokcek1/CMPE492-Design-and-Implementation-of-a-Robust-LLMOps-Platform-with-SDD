"""CRUD for deployment_monitoring rows."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from ..db import get_session_factory
from ..db.models import DeploymentMonitoringRow


class MetricsStore:
    def create_active(
        self,
        *,
        deployment_id: str,
        user_id: str,
        scrape_job: str,
        grafana_datasource_uid: str,
        grafana_dashboard_uid: str,
    ) -> DeploymentMonitoringRow:
        now = datetime.now(UTC)
        session_factory = get_session_factory()
        with session_factory() as db:
            existing = db.execute(
                select(DeploymentMonitoringRow).where(
                    DeploymentMonitoringRow.deployment_id == deployment_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.status = "active"
                existing.prometheus_scrape_job = scrape_job
                existing.grafana_datasource_uid = grafana_datasource_uid
                existing.grafana_dashboard_uid = grafana_dashboard_uid
                existing.decommission_at = None
                existing.updated_at = now
                db.commit()
                db.refresh(existing)
                db.expunge(existing)
                return existing

            row = DeploymentMonitoringRow(
                deployment_id=deployment_id,
                user_id=user_id,
                prometheus_scrape_job=scrape_job,
                grafana_datasource_uid=grafana_datasource_uid,
                grafana_dashboard_uid=grafana_dashboard_uid,
                status="active",
                provisioned_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def get_for_deployment(self, deployment_id: str) -> DeploymentMonitoringRow | None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentMonitoringRow).where(
                    DeploymentMonitoringRow.deployment_id == deployment_id
                )
            ).scalar_one_or_none()
            if row is not None:
                db.expunge(row)
            return row

    def mark_decommissioning(self, *, deployment_id: str, decommission_at: datetime) -> None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentMonitoringRow).where(
                    DeploymentMonitoringRow.deployment_id == deployment_id
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = "decommissioning"
            row.decommission_at = decommission_at
            row.updated_at = datetime.now(UTC)
            db.commit()

    def list_due_for_decommission(self, *, now: datetime) -> list[DeploymentMonitoringRow]:
        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.execute(
                select(DeploymentMonitoringRow).where(
                    DeploymentMonitoringRow.status == "decommissioning",
                    DeploymentMonitoringRow.decommission_at <= now,
                )
            ).scalars().all()
            for row in rows:
                db.expunge(row)
            return list(rows)

    def delete(self, deployment_id: str) -> None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentMonitoringRow).where(
                    DeploymentMonitoringRow.deployment_id == deployment_id
                )
            ).scalar_one_or_none()
            if row is not None:
                db.delete(row)
                db.commit()


metrics_store = MetricsStore()

__all__ = ["MetricsStore", "metrics_store"]
