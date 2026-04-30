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
    # US2 — project/billing/cluster lifecycle                            #
    # ------------------------------------------------------------------ #
    async def create_project(self, user_id: str, deployment_id: str, project_id: str) -> str:
        import asyncio

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import resourcemanager_v3

        parent = await _resolve_parent_for_user(user_id)
        sa_email = await _sa_email_for_user(user_id)

        def _create() -> None:
            creds = _saved_credentials_for_user(user_id)
            client = resourcemanager_v3.ProjectsClient(credentials=creds)
            project = resourcemanager_v3.Project(
                project_id=project_id,
                display_name=f"llmops {deployment_id[:8]}",
            )
            if parent:
                project.parent = parent
            try:
                op = client.create_project(project=project)
                op.result(timeout=600)
            except gcp_exceptions.PermissionDenied as exc:
                raise _project_create_permission_error(
                    parent=parent, sa_email=sa_email, raw_message=exc.message or ""
                ) from exc
            except gcp_exceptions.InvalidArgument as exc:
                # e.g. malformed parent id → surface clearly
                raise GCPProviderError(f"Project creation rejected: {exc.message}") from exc
            except gcp_exceptions.AlreadyExists as exc:
                raise GCPProviderError(
                    f"GCP project id {project_id} is already taken; please retry."
                ) from exc
            except gcp_exceptions.GoogleAPICallError as exc:
                raise GCPTransientError(f"Transient error during project create: {exc.message}") from exc

        await asyncio.get_event_loop().run_in_executor(None, _create)
        return project_id

    async def enable_services(self, project_id: str) -> None:
        import asyncio

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import service_usage_v1

        def _enable() -> None:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = service_usage_v1.ServiceUsageClient(credentials=creds)
            service_names = [
                "compute.googleapis.com",
                "container.googleapis.com",
                "cloudbilling.googleapis.com",
            ]
            try:
                op = client.batch_enable_services(
                    request=service_usage_v1.BatchEnableServicesRequest(
                        parent=f"projects/{project_id}",
                        service_ids=service_names,
                    )
                )
                op.result(timeout=600)
            except gcp_exceptions.PermissionDenied as exc:
                raise GCPAuthError(
                    f"Enabling services refused by GCP: {exc.message}. "
                    "Grant your service account 'roles/serviceusage.serviceUsageAdmin' "
                    "at the Organization/Folder level so it can activate APIs on "
                    "projects it creates."
                ) from exc
            except gcp_exceptions.FailedPrecondition as exc:
                # Almost always "Billing account for project 'N' is not found".
                # Our orchestrator attaches billing before this step, so hitting
                # this usually means billing propagation hasn't completed or the
                # SA's billing grant is missing.
                msg = exc.message or ""
                if "billing" in msg.lower():
                    raise GCPProviderError(
                        "GCP refused to enable APIs because the new project has no "
                        "billing account attached. This typically means either:\n"
                        "  (a) the attach-billing step silently failed — check your "
                        "service account has 'roles/billing.user' on your billing "
                        "account (not just on the org);\n"
                        "  (b) the billing account id you saved is wrong;\n"
                        "  (c) your billing account is closed / suspended.\n\n"
                        "Grant the role with:\n\n"
                        '  gcloud billing accounts add-iam-policy-binding <BILLING-ACCOUNT-ID> \\\n'
                        '      --member="serviceAccount:<YOUR-SA-EMAIL>" \\\n'
                        '      --role="roles/billing.user"\n\n'
                        f"Raw GCP message: {msg}"
                    ) from exc
                raise GCPProviderError(f"Enable-services precondition failed: {msg}") from exc
            except gcp_exceptions.GoogleAPICallError as exc:
                raise GCPTransientError(f"Transient error enabling services: {exc.message}") from exc

        await asyncio.get_event_loop().run_in_executor(None, _enable)

    async def attach_billing(self, project_id: str, billing_account_id: str) -> None:
        import asyncio

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import billing_v1

        def _attach() -> None:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = billing_v1.CloudBillingClient(credentials=creds)
            try:
                info = client.update_project_billing_info(
                    name=f"projects/{project_id}",
                    project_billing_info=billing_v1.ProjectBillingInfo(
                        billing_account_name=billing_account_id,
                    ),
                )
                # Verify the attachment actually stuck. update_project_billing_info
                # can silently return an un-billed ProjectBillingInfo if the SA
                # lacks the role on the billing account (confusingly, it does NOT
                # raise PermissionDenied in that case).
                if not info.billing_enabled:
                    raise GCPProviderError(
                        f"GCP accepted the attach-billing call but the project is still "
                        f"not billing-enabled. Your service account likely lacks "
                        f"'roles/billing.user' on billing account '{billing_account_id}'. "
                        "Grant it with:\n\n"
                        f'  gcloud billing accounts add-iam-policy-binding {billing_account_id.removeprefix("billingAccounts/")} \\\n'
                        '      --member="serviceAccount:<YOUR-SA-EMAIL>" \\\n'
                        '      --role="roles/billing.user"'
                    )
            except gcp_exceptions.PermissionDenied as exc:
                raise GCPAuthError(
                    f"Attaching billing refused: {exc.message}. Grant your service "
                    f"account 'roles/billing.user' on billing account "
                    f"'{billing_account_id}'."
                ) from exc
            except gcp_exceptions.NotFound as exc:
                raise GCPProviderError(
                    f"Billing account '{billing_account_id}' does not exist or is "
                    f"not visible to the service account: {exc.message}"
                ) from exc
            except gcp_exceptions.FailedPrecondition as exc:
                # e.g. "Cloud billing quota exceeded" on free-trial accounts
                # (capped at ~5 concurrent billed projects). NOT transient —
                # retrying won't help until the user frees a slot.
                raw = _format_precondition_violations(exc)
                if "billing quota" in raw.lower() or "quota exceeded" in raw.lower():
                    raise GCPProviderError(
                        f"Billing account '{billing_account_id}' cannot accept another "
                        "linked project — its per-account quota for concurrent billed "
                        "projects has been reached. This is a common ceiling on "
                        "free-trial ($300-credit) accounts, which are typically capped "
                        "at 5 simultaneously-billed projects.\n\n"
                        "Fix by deleting dangling projects this billing account is still "
                        "linked to:\n\n"
                        "  # List them:\n"
                        f'  gcloud billing projects list --billing-account={billing_account_id.removeprefix("billingAccounts/")}\n\n'
                        "  # Delete the ones you no longer need (e.g. failed deploys):\n"
                        '  gcloud projects delete <PROJECT-ID>\n\n'
                        "Deleted projects are PERMANENTLY removed after ~30 days; the "
                        "billing slot is freed within a few minutes of the delete call. "
                        "Alternatively, request a quota increase at "
                        "https://support.google.com/code/contact/billing_quota_increase.\n\n"
                        f"Raw GCP violation: {raw}"
                    ) from exc
                # Other precondition failures on attach_billing are still not
                # transient — surface the raw message.
                raise GCPProviderError(
                    f"Attach-billing precondition failed: {raw or exc.message}"
                ) from exc
            except gcp_exceptions.GoogleAPICallError as exc:
                raise GCPTransientError(f"Transient error attaching billing: {exc.message}") from exc

        await asyncio.get_event_loop().run_in_executor(None, _attach)

    async def create_gke_cluster(
        self,
        project_id: str,
        cluster_name: str,
        region: str,
    ) -> ClusterHandle:
        import asyncio

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import container_v1

        def _create() -> ClusterHandle:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = container_v1.ClusterManagerClient(credentials=creds)
            parent = f"projects/{project_id}/locations/{region}"
            cluster = container_v1.Cluster(
                name=cluster_name,
                autopilot=container_v1.Autopilot(enabled=True),
                initial_cluster_version="latest",
            )
            try:
                op = client.create_cluster(parent=parent, cluster=cluster)
                # Polling: wait for cluster READY. The GKE SDK provides a wait helper.
                import time

                deadline = time.monotonic() + 1800
                while time.monotonic() < deadline:
                    op = client.get_operation(
                        name=f"{parent}/operations/{op.name.split('/')[-1]}"
                    )
                    if op.status == container_v1.Operation.Status.DONE:
                        break
                    time.sleep(15)
                got = client.get_cluster(name=f"{parent}/clusters/{cluster_name}")
                return ClusterHandle(
                    project_id=project_id,
                    cluster_name=cluster_name,
                    region=region,
                    endpoint=got.endpoint,
                    ca_certificate=got.master_auth.cluster_ca_certificate,
                    kubeconfig_yaml=_build_kubeconfig(
                        endpoint=got.endpoint,
                        ca_cert=got.master_auth.cluster_ca_certificate,
                        project_id=project_id,
                        cluster_name=cluster_name,
                        region=region,
                        sa_json=_saved_sa_json_for_project(project_id),
                    ),
                )
            except gcp_exceptions.PermissionDenied as exc:
                raise GCPAuthError(f"Cluster creation refused: {exc.message}") from exc
            except gcp_exceptions.GoogleAPICallError as exc:
                raise GCPTransientError(f"Transient error creating cluster: {exc.message}") from exc

        return await asyncio.get_event_loop().run_in_executor(None, _create)

    async def get_kube_config(self, project_id: str, cluster_name: str, region: str) -> str:
        import asyncio

        from google.cloud import container_v1

        def _get() -> str:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = container_v1.ClusterManagerClient(credentials=creds)
            got = client.get_cluster(
                name=f"projects/{project_id}/locations/{region}/clusters/{cluster_name}"
            )
            return _build_kubeconfig(
                endpoint=got.endpoint,
                ca_cert=got.master_auth.cluster_ca_certificate,
                project_id=project_id,
                cluster_name=cluster_name,
                region=region,
                sa_json=_saved_sa_json_for_project(project_id),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _get)

    async def delete_project(self, project_id: str) -> None:
        import asyncio

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import resourcemanager_v3

        def _delete() -> None:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = resourcemanager_v3.ProjectsClient(credentials=creds)
            try:
                op = client.delete_project(name=f"projects/{project_id}")
                op.result(timeout=600)
            except gcp_exceptions.NotFound:
                return
            except gcp_exceptions.PermissionDenied as exc:
                raise GCPAuthError(f"Project delete refused: {exc.message}") from exc
            except gcp_exceptions.GoogleAPICallError as exc:
                raise GCPTransientError(f"Transient error deleting project: {exc.message}") from exc

        await asyncio.get_event_loop().run_in_executor(None, _delete)

    async def project_exists(self, project_id: str) -> bool:
        import asyncio
        import logging

        from google.api_core import exceptions as gcp_exceptions
        from google.cloud import resourcemanager_v3

        log = logging.getLogger("llmops.gcp.real_provider")

        def _check() -> bool:
            creds = _saved_credentials_for_user_for_project(project_id)
            client = resourcemanager_v3.ProjectsClient(credentials=creds)
            try:
                project = client.get_project(name=f"projects/{project_id}")
                # Projects being deleted are still fetchable but have state DELETE_REQUESTED
                return project.state == resourcemanager_v3.Project.State.ACTIVE
            except gcp_exceptions.NotFound:
                return False
            except gcp_exceptions.PermissionDenied:
                # GCP returns the exact same PermissionDenied whether the project
                # doesn't exist OR the caller can't see it. That's deliberate on
                # their side (prevents project-id enumeration) but bad for us —
                # if we raised here, the 30s status-refresh loop would (a) flood
                # logs, and (b) flip the user's credentials to ``invalid`` via
                # ``_wrap`` in the orchestrator even when the SA is perfectly
                # fine at every other operation.
                #
                # Conservative choice: treat "can't determine" as "still exists".
                # Worst case we miss a ``lost`` transition — fine, the user will
                # see that when they manually hit delete. Better than spuriously
                # invalidating their credentials.
                log.debug(
                    "project_exists(%s): caller lacks resourcemanager.projects.get; "
                    "assuming project still exists. Grant the SA "
                    "'roles/resourcemanager.projectViewer' on your Org/Folder if "
                    "you want accurate lost-project detection.",
                    project_id,
                )
                return True

        return await asyncio.get_event_loop().run_in_executor(None, _check)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _format_precondition_violations(exc: Exception) -> str:
    """Extract the hidden ``violations`` attached to a FailedPrecondition.

    google-api-core stringifies FailedPrecondition as
    ``"Precondition check failed."`` which hides the actually-useful
    ``subject`` + ``description`` pairs. We dig into ``exc.details`` (a list of
    proto messages) and surface them.
    """
    parts: list[str] = []
    # google-api-core attaches structured details on ``.details``
    details = getattr(exc, "details", None) or ()
    for detail in details:
        # PreconditionFailure has a repeated ``violations`` field with
        # subject/description
        violations = getattr(detail, "violations", None) or ()
        for v in violations:
            subject = getattr(v, "subject", "") or ""
            description = getattr(v, "description", "") or ""
            if subject or description:
                parts.append(f"{subject}: {description}".strip(" :"))
    if parts:
        return "; ".join(parts)
    # Fallback to whatever google-api-core stringifies
    return str(exc)


async def _resolve_parent_for_user(user_id: str) -> str | None:
    """Return the Organization/Folder parent saved for this user, or None.

    Keeping this outside ``_saved_credentials_for_user`` because the parent is
    stored plaintext (not a secret) and the DB lookup is cheap.
    """
    from .credentials_store import credentials_store

    return await credentials_store.get_parent(user_id=user_id)


async def _sa_email_for_user(user_id: str) -> str | None:
    """Look up the stored service-account email for a user (plaintext column)."""
    from sqlalchemy import select

    from ..db import get_session_factory
    from ..db.models import GCPCredentialsRow

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
        ).scalar_one_or_none()
    return row.service_account_email if row is not None else None


def _project_create_permission_error(
    *,
    parent: str | None,
    sa_email: str | None,
    raw_message: str,
):
    """Build an actionable GCP-provider error for a ``create_project`` 403.

    The raw gRPC message is almost never helpful ("The caller does not have
    permission"); this helper attaches the exact ``gcloud`` incantation the
    user needs to run, preloaded with their SA email and configured parent.
    Returns a ``GCPProviderError`` (not ``GCPAuthError``) because a missing
    IAM grant on the parent is distinct from the user's saved credentials
    being revoked — we don't want this to flip ``validation_status`` to
    ``invalid``.
    """
    msg_lower = raw_message.lower()

    # Case 1: parent was not set → the GCP message is explicit about it.
    if (
        "without a parent" in msg_lower
        or ("parent" in msg_lower and "service account" in msg_lower)
        or parent is None
    ):
        return GCPProviderError(
            "Service accounts cannot create GCP projects without a parent. "
            "Open the **☁️ GCP Credentials** tab, fill in the "
            "'Deployment parent' field with 'organizations/<NUMERIC-ID>' "
            "or 'folders/<NUMERIC-ID>', and make sure your service account "
            "has the 'roles/resourcemanager.projectCreator' role on that parent. "
            + (f"Raw GCP message: {raw_message}" if raw_message else "")
        )

    # Case 2: parent was set but the SA lacks permission on it.
    parent_kind, _, parent_id = parent.partition("/")
    grant_cmd = (
        f"gcloud {parent_kind} add-iam-policy-binding {parent_id} \\\n"
        f'    --member="serviceAccount:{sa_email or "<YOUR-SA-EMAIL>"}" \\\n'
        '    --role="roles/resourcemanager.projectCreator"'
    )
    billing_cmd = (
        f"gcloud {parent_kind} add-iam-policy-binding {parent_id} \\\n"
        f'    --member="serviceAccount:{sa_email or "<YOUR-SA-EMAIL>"}" \\\n'
        '    --role="roles/billing.user"'
    )

    return GCPProviderError(
        f"GCP rejected project creation on parent '{parent}' with "
        '"The caller does not have permission". This almost always means the '
        "service account is missing the 'roles/resourcemanager.projectCreator' "
        "role on that "
        f"{parent_kind.rstrip('s')}.\n\n"
        f"Grant it with:\n\n{grant_cmd}\n\n"
        "While you're at it, also grant billing so the next step can attach a "
        f"billing account:\n\n{billing_cmd}\n\n"
        "IAM changes can take up to ~60 seconds to propagate. Retry the deploy "
        "after you've granted the role."
    )


def _saved_credentials_for_user(user_id: str):
    """Look up SA JSON in the credentials_store and return a google-auth object.

    Keeping this as a module-level helper so it is easy to substitute in tests
    (though tests never reach this module because of the import guard).
    """
    import asyncio
    import json as _json

    from google.oauth2 import service_account

    from .crypto import CryptoError
    from .credentials_store import credentials_store

    loop = asyncio.new_event_loop()
    try:
        try:
            tup = loop.run_until_complete(credentials_store.get_decrypted(user_id=user_id))
        except CryptoError as exc:
            raise GCPAuthError(
                "Stored GCP credentials cannot be decrypted because "
                "LLMOPS_ENCRYPTION_KEY changed. Re-save credentials in the "
                "dashboard (or restart backend with the original key) and retry."
            ) from exc
    finally:
        loop.close()
    if tup is None:
        raise GCPAuthError(f"No stored GCP credentials for user {user_id}.")
    sa_json, _ = tup
    return service_account.Credentials.from_service_account_info(
        _json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _saved_credentials_for_user_for_project(project_id: str):
    """When we don't know the user_id inline, resolve via the deployment row.

    Real GCP calls are always made on behalf of the deployment's owning user.
    """

    from sqlalchemy import select

    from ..db import get_session_factory
    from ..db.models import DeploymentRow

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            select(DeploymentRow).where(DeploymentRow.gcp_project_id == project_id)
        ).scalar_one_or_none()
    if row is None:
        raise GCPNotFoundError(f"No deployment row found for project {project_id}.")
    return _saved_credentials_for_user(row.user_id)


def _saved_sa_json_for_project(project_id: str) -> str:
    import asyncio

    from sqlalchemy import select

    from ..db import get_session_factory
    from ..db.models import DeploymentRow
    from .crypto import CryptoError
    from .credentials_store import credentials_store

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            select(DeploymentRow).where(DeploymentRow.gcp_project_id == project_id)
        ).scalar_one_or_none()
    if row is None:
        raise GCPNotFoundError(f"No deployment row for project {project_id}.")

    loop = asyncio.new_event_loop()
    try:
        try:
            tup = loop.run_until_complete(credentials_store.get_decrypted(user_id=row.user_id))
        except CryptoError as exc:
            raise GCPAuthError(
                "Stored GCP credentials cannot be decrypted because "
                "LLMOPS_ENCRYPTION_KEY changed. Re-save credentials in the "
                "dashboard (or restart backend with the original key) and retry."
            ) from exc
    finally:
        loop.close()
    if tup is None:
        raise GCPAuthError(f"No saved credentials for user {row.user_id}.")
    sa_json, _ = tup
    return sa_json


def _build_kubeconfig(
    *,
    endpoint: str,
    ca_cert: str,
    project_id: str,
    cluster_name: str,
    region: str,
    sa_json: str,
) -> str:
    """Build a kubeconfig that authenticates using the stored service account.

    The produced kubeconfig uses a plain Bearer token minted from the SA JSON
    at build-time and written into ``users[].user.token``. The kubernetes
    Python client base64-decodes ``certificate-authority-data`` itself, so the
    value MUST be the already-base64-encoded form that GKE returns from
    ``master_auth.cluster_ca_certificate`` — re-encoding it produces invalid
    PEM and triggers     ``[X509: NO_CERTIFICATE_OR_CRL_FOUND]`` at SSL handshake.
    """
    import json as _json

    import google.auth.transport.requests
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        _json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    token = creds.token or ""

    ca_b64 = _normalize_ca_b64(ca_cert)

    return (
        "apiVersion: v1\n"
        "kind: Config\n"
        "clusters:\n"
        f"- name: {cluster_name}\n"
        "  cluster:\n"
        f"    server: https://{endpoint}\n"
        f"    certificate-authority-data: {ca_b64}\n"
        "contexts:\n"
        f"- name: {cluster_name}-ctx\n"
        "  context:\n"
        f"    cluster: {cluster_name}\n"
        "    user: llmops-sa\n"
        "users:\n"
        "- name: llmops-sa\n"
        "  user:\n"
        f"    token: {token}\n"
        f"current-context: {cluster_name}-ctx\n"
    )


def _normalize_ca_b64(ca_cert: str) -> str:
    """Return the cluster CA in the base64 form expected by kubeconfig.

    GKE's ``master_auth.cluster_ca_certificate`` is documented to return the
    cert *already* base64-encoded, so the common case is to pass it straight
    through (after stripping any whitespace/newlines that crept in). If we
    ever receive the cert in raw PEM form (e.g. starting with
    ``-----BEGIN CERTIFICATE-----``), we base64-encode it once. We never
    encode twice.
    """
    import base64
    import binascii

    if not ca_cert:
        return ""

    stripped = "".join(ca_cert.split())  # strip newlines/whitespace
    if "BEGINCERTIFICATE" in stripped or ca_cert.lstrip().startswith("-----BEGIN"):
        # Raw PEM → encode once.
        return base64.b64encode(ca_cert.encode("utf-8")).decode("ascii")

    # Defensive: confirm the value is valid base64. If it isn't, fall back to
    # encoding the raw bytes once. Either branch produces exactly one layer
    # of base64 in the kubeconfig.
    try:
        base64.b64decode(stripped, validate=True)
        return stripped
    except (binascii.Error, ValueError):
        return base64.b64encode(ca_cert.encode("utf-8")).decode("ascii")


__all__ = ["RealGCPProvider"]
