from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class GCPProviderError(Exception):
    """Base class for structured GCPProvider failures.

    Every provider method raises one of the subclasses below so callers can
    distinguish retryable vs terminal failures and, importantly, can detect
    auth/permission failures to flip `gcp_credentials.validation_status`
    without parsing string messages.
    """

    code: str = "provider_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GCPAuthError(GCPProviderError):
    """Raised when GCP rejects the caller's credentials (PermissionDenied / Unauthenticated)."""

    code = "auth_error"


class GCPQuotaError(GCPProviderError):
    """Raised when a create operation is refused because of quota / billing."""

    code = "quota_error"


class GCPNotFoundError(GCPProviderError):
    """Raised when a resource we expected no longer exists (e.g. project was deleted out-of-band)."""

    code = "not_found"


class GCPTransientError(GCPProviderError):
    """Retryable infrastructure / network error."""

    code = "transient"


@dataclass(frozen=True)
class ValidationResult:
    service_account_email: str
    gcp_project_id_of_sa: str
    billing_account_id: str


@dataclass(frozen=True)
class ClusterHandle:
    project_id: str
    cluster_name: str
    region: str
    endpoint: str
    ca_certificate: str
    kubeconfig_yaml: str


class GCPProvider(Protocol):
    """Single dependency-injection boundary between platform code and real GCP APIs.

    A `FakeGCPProvider` with the same surface is used in every automated test.
    No test in this codebase imports the real `google.cloud.*` clients — see
    the import-guard test in `tests/contract/test_test_isolation.py`.
    """

    async def validate_credentials(self, sa_json: str, billing_account_id: str) -> ValidationResult:
        ...

    async def create_project(self, user_id: str, deployment_id: str) -> str:
        """Create a brand-new GCP project and return its project_id."""
        ...

    async def enable_services(self, project_id: str) -> None:
        """Enable the APIs we need (Compute, Container, CloudBilling)."""
        ...

    async def attach_billing(self, project_id: str, billing_account_id: str) -> None:
        ...

    async def create_gke_cluster(
        self,
        project_id: str,
        cluster_name: str,
        region: str,
    ) -> ClusterHandle:
        ...

    async def get_kube_config(self, project_id: str, cluster_name: str, region: str) -> str:
        """Return a kubeconfig YAML string scoped to the given cluster."""
        ...

    async def delete_project(self, project_id: str) -> None:
        ...

    async def project_exists(self, project_id: str) -> bool:
        ...


__all__ = [
    "GCPProvider",
    "GCPProviderError",
    "GCPAuthError",
    "GCPQuotaError",
    "GCPNotFoundError",
    "GCPTransientError",
    "ValidationResult",
    "ClusterHandle",
]
