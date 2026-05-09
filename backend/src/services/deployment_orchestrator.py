"""Async state machine that drives a deployment from ``queued`` to terminal.

Called by:

- ``POST /api/deployments``       → schedules ``run_to_terminal`` as a
                                     background task so the HTTP response
                                     can return 202 immediately.
- Lifespan status-refresh task    → calls ``refresh_statuses`` on a timer
                                     to flip running-but-ghost rows to
                                     ``lost``.
- ``DELETE /api/deployments/{id}`` → calls ``request_deletion`` which
                                     cancels any in-flight deploy, then
                                     tears down GCP resources.

Every GCPProvider call is wrapped so that ``PermissionDenied`` /
``Unauthenticated`` failures (translated to ``GCPAuthError``) flip the
owning user's ``gcp_credentials.validation_status`` to ``invalid`` (FR-015 /
T062a). Running deployments are NEVER touched as a side effect of that
flip — only the NEW deploys/deletes are blocked (that block lives in the
API layer).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Awaitable, Callable

from ..db.models import DeploymentRow
from .credentials_store import credentials_store
from .deployment_store import deployment_store
from .gcp_provider import (
    ClusterHandle,
    GCPAuthError,
    GCPNotFoundError,
    GCPProvider,
    GCPProviderError,
    GCPQuotaError,
    GCPTransientError,
)

logger = logging.getLogger("llmops.orchestrator")

_STATUS_REFRESH_INTERVAL_SECONDS = 30


class DeploymentOrchestrator:
    def __init__(self) -> None:
        # Active deploy tasks keyed by deployment_id so we can cancel from
        # another coroutine (used by the delete flow).
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._status_refresh_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    # High-level entry points                                            #
    # ------------------------------------------------------------------ #
    def schedule(self, deployment_id: str, provider: GCPProvider) -> asyncio.Task:
        """Kick off the state-machine as a fire-and-forget task."""
        task = asyncio.create_task(self.run_to_terminal(deployment_id, provider))
        self._active_tasks[deployment_id] = task

        def _cleanup(t: asyncio.Task) -> None:
            self._active_tasks.pop(deployment_id, None)

        task.add_done_callback(_cleanup)
        return task

    async def run_to_terminal(self, deployment_id: str, provider: GCPProvider) -> None:
        """Drive ``queued → deploying → running`` or ``failed`` (with cleanup)."""
        row = deployment_store.get(deployment_id)
        if row is None:
            logger.warning("Deployment %s vanished before orchestrator picked it up.", deployment_id)
            return

        if row.status != "queued":
            logger.info(
                "Skipping orchestrator for %s: not in queued state (%s).", deployment_id, row.status
            )
            return

        user_id = row.user_id
        project_id = row.gcp_project_id

        def set_status(status: str, message: str | None = None, endpoint_url: str | None = None) -> None:
            deployment_store.update_status(
                deployment_id=deployment_id,
                status=status,
                status_message=message,
                endpoint_url=endpoint_url,
            )

        set_status("deploying", "Creating GCP project…")

        # Track whether ``create_project`` actually succeeded so that on a
        # later-step failure we only roll back *real* partial resources. If
        # ``create_project`` itself fails, there is nothing to tear down —
        # and attempting a delete would just produce a second misleading
        # PermissionDenied traceback.
        #
        # We also track whether the GKE cluster came up. Cluster bring-up on
        # Autopilot takes ~15-25 minutes; once it succeeds, throwing it away
        # on a downstream manifest-apply / endpoint-resolve failure is a
        # terrible UX (esp. for transient kube-apply errors). We instead
        # leave the project in place and surface a ``failed`` status with a
        # message telling the user to delete via the UI when they're ready,
        # which still tears down the project end-to-end (FR-009 is satisfied
        # via that explicit user-driven path rather than auto-cleanup).
        project_created = False
        cluster_created = False

        try:
            await _wrap(
                provider.create_project(user_id=user_id, deployment_id=deployment_id, project_id=project_id),
                user_id=user_id,
            )
            project_created = True
            set_status("deploying", "Attaching billing account…")

            # Attach billing FIRST. GCP refuses to activate any billable API
            # (compute/container/artifact registry/etc.) on a project until a
            # billing account is linked — so `enable_services` MUST run after
            # this step, not before.
            billing_account_id = await credentials_store.get_billing_account_id(user_id=user_id)
            if billing_account_id is None:
                raise GCPProviderError(
                    "Credentials were removed while the deployment was in-flight."
                )

            await _wrap(
                provider.attach_billing(project_id=project_id, billing_account_id=billing_account_id),
                user_id=user_id,
            )
            set_status("deploying", "Enabling required GCP services…")

            await _wrap(provider.enable_services(project_id=project_id), user_id=user_id)
            set_status("deploying", "Provisioning GKE Autopilot cluster…")

            cluster_handle: ClusterHandle = await _wrap(
                provider.create_gke_cluster(
                    project_id=project_id,
                    cluster_name=row.gke_cluster_name,
                    region=row.gke_region,
                ),
                user_id=user_id,
            )
            cluster_created = True
            set_status("deploying", "Refreshing cluster credentials…")

            # Re-fetch the kubeconfig with a fresh token — the one bundled in
            # ``cluster_handle`` may have already expired on a slow bring-up.
            fresh_kubeconfig = await _wrap(
                provider.get_kube_config(
                    project_id=project_id,
                    cluster_name=row.gke_cluster_name,
                    region=row.gke_region,
                ),
                user_id=user_id,
            )
            cluster_handle = ClusterHandle(
                project_id=cluster_handle.project_id,
                cluster_name=cluster_handle.cluster_name,
                region=cluster_handle.region,
                endpoint=cluster_handle.endpoint,
                ca_certificate=cluster_handle.ca_certificate,
                kubeconfig_yaml=fresh_kubeconfig,
            )
            set_status("deploying", "Deploying CPU inference server…")

            endpoint_url = await _apply_manifests_and_get_endpoint(
                provider=provider,
                row=row,
                cluster_handle=cluster_handle,
            )

            set_status("running", "Inference server is ready.", endpoint_url=endpoint_url)
            logger.info("Deployment %s reached RUNNING at %s", deployment_id, endpoint_url)
        except asyncio.CancelledError:
            logger.info("Deployment %s was cancelled by user-initiated deletion.", deployment_id)
            # The delete flow owns the teardown; we just stop here.
            raise
        except GCPProviderError as exc:
            logger.exception("Deployment %s failed: %s", deployment_id, exc)
            set_status("failed", _format_failure_message(exc, cluster_created=cluster_created))
            if project_created and not cluster_created:
                await _best_effort_rollback(provider, project_id)
            elif cluster_created:
                logger.info(
                    "Deployment %s failed AFTER cluster %s was up — leaving the "
                    "GCP project %s in place so the user can inspect / retry / "
                    "delete via the UI (Autopilot bring-up is slow, auto-rollback "
                    "would discard ~15-25 min of provisioning).",
                    deployment_id, row.gke_cluster_name, project_id,
                )
        except Exception as exc:  # noqa: BLE001 — capture final safety net
            logger.exception("Deployment %s failed with unexpected error.", deployment_id)
            set_status(
                "failed",
                _format_unexpected_failure_message(exc, cluster_created=cluster_created),
            )
            if project_created and not cluster_created:
                await _best_effort_rollback(provider, project_id)
            elif cluster_created:
                logger.info(
                    "Deployment %s failed AFTER cluster %s was up — leaving the "
                    "GCP project %s in place so the user can inspect / retry / "
                    "delete via the UI.",
                    deployment_id, row.gke_cluster_name, project_id,
                )

    async def request_deletion(self, deployment_id: str, provider: GCPProvider) -> None:
        """Cancel any in-flight deploy + tear down the project."""
        row = deployment_store.get(deployment_id)
        if row is None:
            return

        if row.status in ("deleted", "deleting"):
            return

        if row.status == "lost":
            deployment_store.hard_delete(deployment_id)
            return

        # Cancel the deploy task if it's still running.
        task = self._active_tasks.pop(deployment_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        deployment_store.update_status(
            deployment_id=deployment_id,
            status="deleting",
            status_message="Tearing down GCP project…",
        )

        try:
            await _wrap(provider.delete_project(project_id=row.gcp_project_id), user_id=row.user_id)
            deployment_store.update_status(
                deployment_id=deployment_id,
                status="deleted",
                status_message="GCP project deleted.",
                deleted_at=datetime.now(UTC),
            )
        except GCPNotFoundError:
            # Project already gone → treat as successful delete.
            deployment_store.update_status(
                deployment_id=deployment_id,
                status="deleted",
                status_message="GCP project was already absent.",
                deleted_at=datetime.now(UTC),
            )
        except GCPProviderError as exc:
            logger.exception("Delete of deployment %s failed: %s", deployment_id, exc)
            deployment_store.update_status(
                deployment_id=deployment_id,
                status="failed",
                status_message=f"Delete failed: {exc.message}. You may retry.",
            )

    async def refresh_statuses(self, provider: GCPProvider) -> None:
        """Flip running/deploying deployments to ``lost`` when their project vanishes."""
        rows = deployment_store.list_needing_status_refresh()
        for row in rows:
            try:
                exists = await _wrap(
                    provider.project_exists(project_id=row.gcp_project_id),
                    user_id=row.user_id,
                )
            except GCPProviderError as exc:
                # Demote to DEBUG: the real-provider path now returns True on
                # PermissionDenied (see gcp_real_provider.project_exists), so
                # reaching this branch in practice means a genuinely unusual
                # GCP condition, not a recurring permission gap. We keep the
                # log line so it's still discoverable when debugging, just not
                # at WARNING once every 30 s.
                logger.debug(
                    "Status refresh for %s (project %s) skipped: %s",
                    row.id, row.gcp_project_id, exc,
                )
                continue

            if not exists and row.status in ("running", "deploying"):
                deployment_store.update_status(
                    deployment_id=row.id,
                    status="lost",
                    status_message=(
                        "The GCP project backing this deployment no longer exists "
                        "(it was likely deleted outside the platform)."
                    ),
                )

    async def start_status_refresh_loop(self, provider_factory: Callable[[], GCPProvider]) -> None:
        """Background coroutine that polls every 30s on FastAPI lifespan."""
        try:
            while True:
                await asyncio.sleep(_STATUS_REFRESH_INTERVAL_SECONDS)
                try:
                    await self.refresh_statuses(provider=provider_factory())
                except Exception:  # noqa: BLE001 — never kill the loop
                    logger.exception("Status refresh tick failed.")
        except asyncio.CancelledError:
            return


deployment_orchestrator = DeploymentOrchestrator()


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

async def _wrap(awaitable: Awaitable, *, user_id: str):
    """Invoke an awaitable and translate any GCPAuthError into a credential
    invalidation side-effect (FR-015 / T062a).
    """
    try:
        return await awaitable
    except GCPAuthError as exc:
        # Flip the credential row to invalid so future POST/DELETE /api/deployments are blocked.
        try:
            await credentials_store.record_credentials_invalid(user_id=user_id, error=exc)
        except Exception:  # noqa: BLE001 — don't mask the original failure
            logger.exception("Failed to record credentials invalid for user %s.", user_id)
        raise


async def _apply_manifests_and_get_endpoint(
    *,
    provider: GCPProvider,
    row: DeploymentRow,
    cluster_handle: ClusterHandle,
) -> str:
    """Apply inference manifests and resolve the LoadBalancer's public URL.

    Fake path (provider is ``FakeGCPProvider``): synthesises a fake IP so
    tests never touch ``kube_client`` → no kubernetes API calls inside
    ``pytest``.
    Real path: delegates to ``kube_client`` helpers.
    """
    from .gcp_fake_provider import FakeGCPProvider

    if isinstance(provider, FakeGCPProvider):
        # Tests get a deterministic fake endpoint URL.
        import hashlib

        h = hashlib.sha1(cluster_handle.project_id.encode()).hexdigest()
        fake_ip = ".".join(str(int(h[i : i + 2], 16) % 200 + 20) for i in range(0, 8, 2))
        return f"http://{fake_ip}:80"

    # Real path: apply manifests, wait for rollout, get LB IP.
    from . import kube_client
    from .vllm_manifest import _safe_name, generate

    hf_token = _hf_token_for_user(row.user_id)
    manifest_yaml = generate(
        hf_model_id=row.hf_model_id,
        hf_token=hf_token,
        cluster_name=row.gke_cluster_name,
    )

    await kube_client.apply_objects(cluster_handle.kubeconfig_yaml, manifest_yaml)
    safe = _safe_name(row.hf_model_id)

    # Stream pod-level progress into deployment.status_message so the UI
    # shows live state ("waiting for L4 node", "pulling image", "loading
    # model", …) instead of a silent ~30-minute spinner.
    deployment_id = row.id

    def _live_status_update(message: str) -> None:
        try:
            deployment_store.update_status(
                deployment_id=deployment_id,
                status="deploying",
                status_message=message,
            )
        except Exception:  # noqa: BLE001 — never let UI updates break the deploy
            logger.exception("Failed to record live status for %s", deployment_id)

    try:
        await kube_client.wait_deployment_available(
            cluster_handle.kubeconfig_yaml,
            f"{safe}-inference",
            status_callback=_live_status_update,
        )
    except kube_client.GpuQuotaExhaustedError as exc:
        # Translate into a structured GCPQuotaError so the failure-message
        # formatter (and any future UI quota-banner logic) can recognise it.
        raise GCPQuotaError(str(exc)) from exc
    except kube_client.ContainerCrashLoopError as exc:
        # Surface as a regular GCPProviderError so the orchestrator records
        # the (already-actionable) message in status_message and does not
        # auto-rollback the cluster (cluster_created is True at this point).
        raise GCPProviderError(str(exc)) from exc

    ip = await kube_client.get_service_lb_ip(cluster_handle.kubeconfig_yaml, f"{safe}-svc")
    return f"http://{ip}:80"


def _hf_token_for_user(user_id: str) -> str:
    """Fetch the platform session HF token for the user so the runtime can pull models.

    For public models this token is technically optional, but the runtime will still use
    it if set, and HF rate-limits anonymous downloads aggressively.
    """
    from .session_store import session_store

    for session in session_store._sessions.values():  # noqa: SLF001 — intentional cross-module read
        if session.username == user_id:
            return session.hf_token
    return ""  # fall back to anonymous


async def _best_effort_rollback(provider: GCPProvider, project_id: str) -> None:
    # Short-circuit if the project doesn't actually exist on GCP. This avoids
    # the misleading second traceback we used to see when ``create_project``
    # itself failed: GCP returns PermissionDenied on the phantom project (the
    # SA never had rights to that project-space in the first place), which
    # hides the real first error under a rollback-failure log line.
    try:
        exists = await provider.project_exists(project_id=project_id)
    except Exception:  # noqa: BLE001 — best-effort probe
        exists = True  # fall through to attempt delete; safer than skipping
    if not exists:
        logger.info(
            "Skipping rollback for project %s — it doesn't exist on GCP "
            "(likely because create_project itself failed).",
            project_id,
        )
        return

    try:
        await provider.delete_project(project_id=project_id)
        logger.info("Rolled back partial resources in project %s.", project_id)
    except GCPNotFoundError:
        return
    except Exception:  # noqa: BLE001 — rollback is best-effort
        logger.exception("Failed to roll back project %s; may require manual cleanup.", project_id)


def _format_failure_message(exc: GCPProviderError, *, cluster_created: bool = False) -> str:
    if isinstance(exc, GCPQuotaError):
        base = f"Quota / billing limit hit: {exc.message}"
    elif isinstance(exc, GCPAuthError):
        base = f"GCP rejected the credentials: {exc.message}"
    elif isinstance(exc, GCPTransientError):
        base = f"Transient cloud error: {exc.message} (you may retry)"
    elif isinstance(exc, GCPNotFoundError):
        base = f"Missing resource during deploy: {exc.message}"
    else:
        base = exc.message
    return _maybe_append_cluster_hint(base, cluster_created=cluster_created)


def _format_unexpected_failure_message(exc: Exception, *, cluster_created: bool = False) -> str:
    return _maybe_append_cluster_hint(
        f"Unexpected error: {exc}",
        cluster_created=cluster_created,
    )


def _maybe_append_cluster_hint(message: str, *, cluster_created: bool) -> str:
    if not cluster_created:
        return message
    return (
        f"{message} The GKE cluster was already provisioned and has NOT been "
        "auto-deleted. Click Delete in the Deployments tab to tear it down "
        "fully when you're ready."
    )


__all__ = ["deployment_orchestrator", "DeploymentOrchestrator"]
