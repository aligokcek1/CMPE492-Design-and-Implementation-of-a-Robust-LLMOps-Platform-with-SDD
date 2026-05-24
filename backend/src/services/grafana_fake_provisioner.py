"""In-memory Grafana provisioner for contract tests."""
from __future__ import annotations


class FakeGrafanaProvisioner:
    def __init__(self) -> None:
        self.provisioned: list[dict] = []
        self.decommissioned: list[dict] = []

    async def provision_dashboard(
        self,
        *,
        deployment_id: str,
        user_id: str,
        datasource_uid: str | None = None,
    ) -> tuple[str, str]:
        ds_uid = datasource_uid or f"dep-{deployment_id.replace('-', '')[:16]}"
        dash_uid = f"dash-{deployment_id.replace('-', '')[:16]}"
        self.provisioned.append(
            {
                "deployment_id": deployment_id,
                "user_id": user_id,
                "datasource_uid": ds_uid,
                "dashboard_uid": dash_uid,
            }
        )
        return ds_uid, dash_uid

    async def decommission(self, *, datasource_uid: str, dashboard_uid: str) -> None:
        self.decommissioned.append(
            {"datasource_uid": datasource_uid, "dashboard_uid": dashboard_uid}
        )


__all__ = ["FakeGrafanaProvisioner"]
