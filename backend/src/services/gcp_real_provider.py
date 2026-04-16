"""Real GCPProvider — talks to actual Google Cloud APIs.

**IMPORTANT (Testing Policy):** This module is lazy-imported only when
``LLMOPS_USE_FAKE_GCP`` is NOT set to ``"1"``. Every automated test in this
repository runs with the fake env flag on, so nothing here is exercised by
pytest. The import-guard test in ``tests/contract/test_test_isolation.py``
actively asserts that ``google.cloud.*`` is absent from ``sys.modules`` during
test runs. If that test fails, a module-level import of this file has leaked.

For feature 007 the real implementation lands incrementally:

- US1 needs ``validate_credentials``     → implemented here.
- US2 needs ``create_project`` / ``enable_services`` / ``attach_billing`` /
  ``create_gke_cluster`` / ``get_kube_config``                → implemented here.
- US3 needs ``project_exists``           → implemented here.
- US4 needs ``delete_project``           → implemented here.

Methods that aren't used yet simply raise ``NotImplementedError`` — they'll come
online as each user story is built out.
"""
from __future__ import annotations

import json

from .gcp_provider import (
    ClusterHandle,
    GCPAuthError,
    GCPNotFoundError,
    GCPProvider,
    GCPProviderError,
    GCPTransientError,
    ValidationResult,
)


_BILLING_PATTERN = r"^billingAccounts/[A-Z0-9-]{20}$"


class RealGCPProvider(GCPProvider):
    async def validate_credentials(self, sa_json: str, billing_account_id: str) -> ValidationResult:
        import re

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
        if not re.fullmatch(_BILLING_PATTERN, billing_account_id):
            raise GCPProviderError(
                "billing_account_id must match pattern billingAccounts/XXXXXX-XXXXXX-XXXXXX."
            )

        # Build google-auth credentials from the parsed SA JSON.
        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import billing_v1, resourcemanager_v3
        from google.oauth2 import service_account

        try:
            credentials = service_account.Credentials.from_service_account_info(
                parsed,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except (ValueError, TypeError) as exc:
            raise GCPProviderError(
                f"Service-account JSON rejected by google-auth: {exc}"
            ) from exc

        # Probe 1: we can list projects (implies the SA + GCP-side auth work).
        try:
            projects_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
            # Passing ``query=""`` + taking the first page is enough to force an auth round-trip.
            projects_pager = projects_client.search_projects(
                request=resourcemanager_v3.SearchProjectsRequest()
            )
            _ = next(iter(projects_pager), None)
        except gcp_exceptions.PermissionDenied as exc:
            raise GCPAuthError(
                f"GCP rejected the service account when listing projects: {exc.message}"
            ) from exc
        except gcp_exceptions.Unauthenticated as exc:
            raise GCPAuthError(
                f"GCP could not authenticate the service account: {exc.message}"
            ) from exc
        except gcp_exceptions.GoogleAPICallError as exc:
            raise GCPTransientError(
                f"Transient error while listing projects: {exc.message}"
            ) from exc

        # Probe 2: we can read the billing account metadata.
        try:
            billing_client = billing_v1.CloudBillingClient(credentials=credentials)
            billing_client.get_billing_account(name=billing_account_id)
        except gcp_exceptions.PermissionDenied as exc:
            raise GCPAuthError(
                "The service account does not have access to the billing account "
                f"{billing_account_id}: {exc.message}"
            ) from exc
        except gcp_exceptions.NotFound as exc:
            raise GCPProviderError(
                f"Billing account {billing_account_id} does not exist or is not visible "
                f"to the service account: {exc.message}"
            ) from exc
        except gcp_exceptions.Unauthenticated as exc:
            raise GCPAuthError(
                f"GCP could not authenticate the service account for billing: {exc.message}"
            ) from exc
        except gcp_exceptions.GoogleAPICallError as exc:
            raise GCPTransientError(
                f"Transient error while reading billing account: {exc.message}"
            ) from exc

        return ValidationResult(
            service_account_email=parsed["client_email"],
            gcp_project_id_of_sa=parsed["project_id"],
            billing_account_id=billing_account_id,
        )

    # ------------------------------------------------------------------ #
    # Methods landing in later user stories.                             #
    # ------------------------------------------------------------------ #
    async def create_project(self, user_id: str, deployment_id: str) -> str:  # noqa: D401
        raise NotImplementedError("create_project lands with US2 implementation.")

    async def enable_services(self, project_id: str) -> None:
        raise NotImplementedError("enable_services lands with US2 implementation.")

    async def attach_billing(self, project_id: str, billing_account_id: str) -> None:
        raise NotImplementedError("attach_billing lands with US2 implementation.")

    async def create_gke_cluster(self, project_id: str, cluster_name: str, region: str) -> ClusterHandle:
        raise NotImplementedError("create_gke_cluster lands with US2 implementation.")

    async def get_kube_config(self, project_id: str, cluster_name: str, region: str) -> str:
        raise NotImplementedError("get_kube_config lands with US2 implementation.")

    async def delete_project(self, project_id: str) -> None:
        raise NotImplementedError("delete_project lands with US4 implementation.")

    async def project_exists(self, project_id: str) -> bool:
        raise NotImplementedError("project_exists lands with US3 implementation.")


__all__ = ["RealGCPProvider"]
