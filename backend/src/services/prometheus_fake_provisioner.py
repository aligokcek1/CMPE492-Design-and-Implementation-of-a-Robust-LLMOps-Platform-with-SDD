"""In-memory Prometheus provisioner for contract tests."""
from __future__ import annotations


class FakePrometheusProvisioner:
    def __init__(self) -> None:
        self.provisioned: list[dict] = []
        self.decommissioned: list[str] = []

    async def provision_scrape_job(
        self,
        *,
        deployment_id: str,
        user_id: str,
        hardware_type: str,
        endpoint_url: str,
    ) -> str:
        scrape_job = f"deployment-{deployment_id}"
        self.provisioned.append(
            {
                "deployment_id": deployment_id,
                "user_id": user_id,
                "hardware_type": hardware_type,
                "endpoint_url": endpoint_url,
                "scrape_job": scrape_job,
            }
        )
        return scrape_job

    async def decommission_scrape_job(self, *, scrape_job: str) -> None:
        self.decommissioned.append(scrape_job)


__all__ = ["FakePrometheusProvisioner"]
