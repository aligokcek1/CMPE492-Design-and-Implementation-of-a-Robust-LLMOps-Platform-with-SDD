from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from typing import Callable

from .gcp_provider import (
    ClusterHandle,
    GCPAuthError,
    GCPNotFoundError,
    GCPProvider,
    GCPProviderError,
    GCPQuotaError,
    GCPTransientError,
    ValidationResult,
)

_VALID_BILLING_ACCOUNT_RE = r"^billingAccounts/[A-Z0-9-]{20}$"

_FailureMap = dict[str, Callable[[], Exception] | None]


@dataclass
class _FakeProject:
    project_id: str
    billing_account_id: str | None = None
    enabled_services: set[str] = field(default_factory=set)
    cluster: ClusterHandle | None = None


class FakeGCPProvider(GCPProvider):
    """In-memory, fully-async GCPProvider implementation used by every automated test.

    Tests can:
      - Seed pre-existing projects via `seed_project(...)`.
      - Inject deterministic failures per method via `fail_on(method=..., error=Exception)`.
      - Inspect call history via `calls`.
    """

    def __init__(self) -> None:
        self._projects: dict[str, _FakeProject] = {}
        self._failures: _FailureMap = {}
        self.calls: list[tuple[str, tuple, dict]] = []
        # Optional artificial delay to exercise async timing paths in tests
        self.artificial_latency_seconds: float = 0.0

    # ---------- test helpers (not part of the GCPProvider protocol) ----------
    def seed_project(self, project_id: str, billing_account_id: str | None = None) -> None:
        self._projects[project_id] = _FakeProject(project_id=project_id, billing_account_id=billing_account_id)

    def fail_on(self, method: str, error: Exception | type[Exception] | None) -> None:
        """Program the next call to `method` to raise `error`.

        Pass `None` to clear.
        """
        if error is None:
            self._failures.pop(method, None)
            return
        if isinstance(error, type):
            err_cls = error
            self._failures[method] = lambda: err_cls("injected failure")
        else:
            self._failures[method] = lambda: error

    def _maybe_fail(self, method: str) -> None:
        factory = self._failures.pop(method, None)
        if factory is not None:
            raise factory()

    async def _yield(self) -> None:
        if self.artificial_latency_seconds > 0:
            await asyncio.sleep(self.artificial_latency_seconds)

    def _record(self, method: str, *args, **kwargs) -> None:
        self.calls.append((method, args, kwargs))

    # ---------- GCPProvider protocol implementation ----------
    async def validate_credentials(self, sa_json: str, billing_account_id: str) -> ValidationResult:
        self._record("validate_credentials", billing_account_id=billing_account_id)
        self._maybe_fail("validate_credentials")
        await self._yield()

        try:
            parsed = json.loads(sa_json)
        except json.JSONDecodeError as exc:
            raise GCPProviderError(f"Service-account JSON is not valid JSON: {exc}") from exc

        for field_name in ("type", "client_email", "private_key", "project_id"):
            if field_name not in parsed:
                raise GCPProviderError(
                    f"Service-account JSON is missing required field '{field_name}'."
                )

        if parsed["type"] != "service_account":
            raise GCPProviderError(
                f"Expected type='service_account', got type={parsed['type']!r}."
            )

        import re
        if not re.fullmatch(_VALID_BILLING_ACCOUNT_RE, billing_account_id):
            raise GCPProviderError(
                "billing_account_id must match pattern billingAccounts/XXXXXX-XXXXXX-XXXXXX."
            )

        return ValidationResult(
            service_account_email=parsed["client_email"],
            gcp_project_id_of_sa=parsed["project_id"],
            billing_account_id=billing_account_id,
        )

    async def create_project(self, user_id: str, deployment_id: str) -> str:
        self._record("create_project", user_id=user_id, deployment_id=deployment_id)
        self._maybe_fail("create_project")
        await self._yield()

        project_id = f"llmops-{secrets.token_hex(4)}-{deployment_id[:6]}"
        self._projects[project_id] = _FakeProject(project_id=project_id)
        return project_id

    async def enable_services(self, project_id: str) -> None:
        self._record("enable_services", project_id=project_id)
        self._maybe_fail("enable_services")
        await self._yield()

        project = self._require(project_id)
        project.enabled_services.update({
            "compute.googleapis.com",
            "container.googleapis.com",
            "cloudbilling.googleapis.com",
        })

    async def attach_billing(self, project_id: str, billing_account_id: str) -> None:
        self._record("attach_billing", project_id=project_id, billing_account_id=billing_account_id)
        self._maybe_fail("attach_billing")
        await self._yield()

        project = self._require(project_id)
        project.billing_account_id = billing_account_id

    async def create_gke_cluster(
        self,
        project_id: str,
        cluster_name: str,
        region: str,
    ) -> ClusterHandle:
        self._record("create_gke_cluster", project_id=project_id, cluster_name=cluster_name, region=region)
        self._maybe_fail("create_gke_cluster")
        await self._yield()

        project = self._require(project_id)
        handle = ClusterHandle(
            project_id=project_id,
            cluster_name=cluster_name,
            region=region,
            endpoint=f"https://fake-gke.{project_id}.example",
            ca_certificate="-----BEGIN FAKE CERT-----",
            kubeconfig_yaml=self._fake_kubeconfig(project_id, cluster_name, region),
        )
        project.cluster = handle
        return handle

    async def get_kube_config(self, project_id: str, cluster_name: str, region: str) -> str:
        self._record("get_kube_config", project_id=project_id, cluster_name=cluster_name, region=region)
        self._maybe_fail("get_kube_config")
        await self._yield()

        project = self._require(project_id)
        if project.cluster is None:
            raise GCPNotFoundError(f"Cluster {cluster_name} not found in project {project_id}.")
        return project.cluster.kubeconfig_yaml

    async def delete_project(self, project_id: str) -> None:
        self._record("delete_project", project_id=project_id)
        self._maybe_fail("delete_project")
        await self._yield()

        if project_id not in self._projects:
            raise GCPNotFoundError(f"Project {project_id} not found.")
        del self._projects[project_id]

    async def project_exists(self, project_id: str) -> bool:
        self._record("project_exists", project_id=project_id)
        self._maybe_fail("project_exists")
        await self._yield()

        return project_id in self._projects

    # ---------- internal helpers ----------
    def _require(self, project_id: str) -> _FakeProject:
        project = self._projects.get(project_id)
        if project is None:
            raise GCPNotFoundError(f"Project {project_id} not found.")
        return project

    @staticmethod
    def _fake_kubeconfig(project_id: str, cluster_name: str, region: str) -> str:
        return (
            "apiVersion: v1\n"
            "kind: Config\n"
            "clusters:\n"
            f"- name: {cluster_name}\n"
            "  cluster:\n"
            f"    server: https://fake-gke.{project_id}.example\n"
            "    certificate-authority-data: LS0tLQ==\n"
            "contexts:\n"
            f"- name: fake-context-{region}\n"
            "  context:\n"
            f"    cluster: {cluster_name}\n"
            "    user: fake-user\n"
            "users:\n"
            "- name: fake-user\n"
            "  user:\n"
            "    token: fake-token\n"
            f"current-context: fake-context-{region}\n"
        )


# Convenience re-exports so tests can raise the real error types from injected failures
__all__ = [
    "FakeGCPProvider",
    "GCPAuthError",
    "GCPQuotaError",
    "GCPNotFoundError",
    "GCPTransientError",
    "GCPProviderError",
]
