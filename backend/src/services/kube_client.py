"""Thin async wrappers around the Kubernetes Python client.

Real GKE apply path; fully isolated from tests by the import-guard. The
orchestrator's fake provider path synthesises fake LB IPs without touching
this module — see ``deployment_orchestrator``.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger("llmops.kube_client")

StatusCallback = Callable[[str], None]


class GpuQuotaExhaustedError(RuntimeError):
    """Raised when pods can never be scheduled because there's no GPU quota.

    Detected via Pod events with reason ``FailedScheduling`` referencing
    insufficient ``nvidia.com/gpu`` resources. We surface this as a distinct
    type so the orchestrator can format a helpful message that points the
    user at the GCP quota request flow.
    """


class ContainerCrashLoopError(RuntimeError):
    """Raised when a pod's container keeps crashing and clearly will not recover.

    We attach the most recent container logs (last few hundred lines) so the
    deployment status surfaced in the UI tells the user *why* the workload
    died, not just that it did. Detected once ``restartCount >= 3`` AND the
    container is back in ``waiting/CrashLoopBackOff`` — at that point we know
    the failure is reproducible and there's no reason to burn the rest of the
    30-minute timeout.
    """


async def apply_objects(kubeconfig_yaml: str, manifest_yaml: str) -> None:
    """Apply Secret + Deployment + Service using the official kubernetes client.

    The kubeconfig_yaml is written to a temp file because the client only loads
    from a file path.
    """
    loop = asyncio.get_event_loop()

    def _apply() -> None:
        from kubernetes import client, config

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
            tmp.write(kubeconfig_yaml)
            kubeconfig_path = tmp.name

        try:
            config.load_kube_config(config_file=kubeconfig_path)
            core_v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()

            for doc in yaml.safe_load_all(manifest_yaml):
                if doc is None:
                    continue
                namespace = doc["metadata"].get("namespace", "default")
                kind = doc["kind"]

                if kind == "Secret":
                    _create_or_replace_secret(core_v1, namespace, doc)
                elif kind == "Deployment":
                    _create_or_replace_deployment(apps_v1, namespace, doc)
                elif kind == "Service":
                    _create_or_replace_service(core_v1, namespace, doc)
                else:
                    raise RuntimeError(f"Unsupported manifest kind: {kind}")
        finally:
            Path(kubeconfig_path).unlink(missing_ok=True)

    await loop.run_in_executor(None, _apply)


def _create_or_replace_secret(core_v1, namespace: str, doc: dict[str, Any]) -> None:
    from kubernetes.client.exceptions import ApiException

    name = doc["metadata"]["name"]
    try:
        core_v1.read_namespaced_secret(name=name, namespace=namespace)
        core_v1.replace_namespaced_secret(name=name, namespace=namespace, body=doc)
    except ApiException as exc:
        if exc.status == 404:
            core_v1.create_namespaced_secret(namespace=namespace, body=doc)
        else:
            raise


def _create_or_replace_deployment(apps_v1, namespace: str, doc: dict[str, Any]) -> None:
    from kubernetes.client.exceptions import ApiException

    name = doc["metadata"]["name"]
    try:
        apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        apps_v1.replace_namespaced_deployment(name=name, namespace=namespace, body=doc)
    except ApiException as exc:
        if exc.status == 404:
            apps_v1.create_namespaced_deployment(namespace=namespace, body=doc)
        else:
            raise


def _create_or_replace_service(core_v1, namespace: str, doc: dict[str, Any]) -> None:
    from kubernetes.client.exceptions import ApiException

    name = doc["metadata"]["name"]
    try:
        existing = core_v1.read_namespaced_service(name=name, namespace=namespace)
        # Services require clusterIP preservation on replace
        doc["spec"]["clusterIP"] = existing.spec.cluster_ip
        core_v1.replace_namespaced_service(name=name, namespace=namespace, body=doc)
    except ApiException as exc:
        if exc.status == 404:
            core_v1.create_namespaced_service(namespace=namespace, body=doc)
        else:
            raise


async def wait_deployment_available(
    kubeconfig_yaml: str,
    deployment_name: str,
    namespace: str = "default",
    timeout_seconds: int = 1800,
    status_callback: StatusCallback | None = None,
    quota_failure_grace_seconds: int = 300,
) -> None:
    """Block until the named Deployment has at least one Available replica.

    Polls the Deployment + its Pods + recent events on a 5-second cadence.
    Whenever the high-level pod state changes (Pending → Pulling → Running →
    Ready) the optional ``status_callback`` is invoked with a short
    human-readable message — the orchestrator wires this into
    ``deployment.status_message`` so the UI shows live progress instead of a
    silent 30-minute blank.

    Fast-fails (raising :class:`GpuQuotaExhaustedError`) if the pod stays
    ``Pending`` with ``FailedScheduling`` events caused by insufficient
    ``nvidia.com/gpu`` for longer than ``quota_failure_grace_seconds``. There
    is no recovery from this without a quota increase, so blocking the full
    30-minute timeout would just waste the user's time.

    On the final timeout, the raised :class:`TimeoutError` includes the
    most recent pod / container / event diagnostics so the orchestrator can
    surface a useful failure message in the UI rather than the bare phrase
    "did not become Available".
    """
    loop = asyncio.get_event_loop()

    def _wait() -> None:
        import time

        from kubernetes import client, config

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
            tmp.write(kubeconfig_yaml)
            kubeconfig_path = tmp.name

        try:
            config.load_kube_config(config_file=kubeconfig_path)
            apps_v1 = client.AppsV1Api()
            core_v1 = client.CoreV1Api()

            deadline = time.monotonic() + timeout_seconds
            quota_first_seen_at: float | None = None
            last_status_message: str | None = None
            last_diagnostics: dict[str, Any] = {}

            while time.monotonic() < deadline:
                try:
                    dep_status = apps_v1.read_namespaced_deployment_status(
                        name=deployment_name, namespace=namespace
                    ).status
                except Exception as exc:  # noqa: BLE001 — diagnostic poll is best-effort
                    logger.debug("Deployment poll failed: %s", exc)
                    dep_status = None

                if dep_status and dep_status.available_replicas and dep_status.available_replicas >= 1:
                    if status_callback is not None:
                        try:
                            status_callback("Inference pod is Ready.")
                        except Exception:  # noqa: BLE001
                            logger.exception("status_callback raised; ignoring.")
                    return

                diagnostics = _collect_pod_diagnostics(
                    core_v1=core_v1,
                    namespace=namespace,
                    deployment_name=deployment_name,
                )
                last_diagnostics = diagnostics

                if diagnostics.get("gpu_quota_failed_scheduling"):
                    if quota_first_seen_at is None:
                        quota_first_seen_at = time.monotonic()
                    elif time.monotonic() - quota_first_seen_at >= quota_failure_grace_seconds:
                        raise GpuQuotaExhaustedError(
                            _format_quota_error(diagnostics)
                        )
                else:
                    quota_first_seen_at = None

                if _is_persistent_crash_loop(diagnostics):
                    raise ContainerCrashLoopError(
                        _format_crashloop_error(core_v1, namespace, diagnostics)
                    )

                msg = _summarize_pod_state(diagnostics)
                if msg and msg != last_status_message:
                    last_status_message = msg
                    logger.info("Deployment %s: %s", deployment_name, msg)
                    if status_callback is not None:
                        try:
                            status_callback(msg)
                        except Exception:  # noqa: BLE001
                            logger.exception("status_callback raised; ignoring.")

                time.sleep(5)

            raise TimeoutError(
                f"Deployment {deployment_name} did not become Available within "
                f"{timeout_seconds}s. {_format_timeout_diagnostics(last_diagnostics)}"
            )
        finally:
            Path(kubeconfig_path).unlink(missing_ok=True)

    await loop.run_in_executor(None, _wait)


# --------------------------------------------------------------------------- #
# Diagnostics helpers                                                         #
# --------------------------------------------------------------------------- #

def _collect_pod_diagnostics(
    *,
    core_v1,
    namespace: str,
    deployment_name: str,
) -> dict[str, Any]:
    """Return a snapshot of the pods/events backing ``deployment_name``.

    We rely on the convention that pods are labeled
    ``app.kubernetes.io/name=<safe>`` where the deployment is
    ``<safe>-inference`` (or legacy ``<safe>-vllm``).
    """
    if deployment_name.endswith("-inference"):
        pod_label_value = deployment_name.removesuffix("-inference")
    elif deployment_name.endswith("-vllm"):
        pod_label_value = deployment_name.removesuffix("-vllm")
    else:
        pod_label_value = deployment_name
    selector = f"app.kubernetes.io/name={pod_label_value}"

    pods_summary: list[dict[str, Any]] = []
    gpu_quota_failed_scheduling = False
    events_summary: list[str] = []

    try:
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=selector).items
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pod list failed: %s", exc)
        pods = []

    for pod in pods:
        phase = getattr(pod.status, "phase", None) or "Unknown"
        container_summary: list[str] = []
        for cs in (pod.status.container_statuses or []):
            state = cs.state
            if state and state.waiting:
                container_summary.append(
                    f"waiting/{state.waiting.reason or '?'}: {state.waiting.message or ''}".strip(": ")
                )
            elif state and state.running:
                container_summary.append("running")
            elif state and state.terminated:
                container_summary.append(
                    f"terminated/{state.terminated.reason or '?'}: {state.terminated.message or ''}".strip(": ")
                )
        if not container_summary:
            container_summary.append("no container status yet")

        crash_loop_container: str | None = None
        max_restart_count = 0
        for cs in (pod.status.container_statuses or []):
            restarts = cs.restart_count or 0
            if restarts > max_restart_count:
                max_restart_count = restarts
            state = cs.state
            if state and state.waiting and state.waiting.reason == "CrashLoopBackOff":
                crash_loop_container = cs.name

        pod_entry = {
            "name": pod.metadata.name,
            "phase": phase,
            "containers": container_summary,
            "restart_count": sum((cs.restart_count or 0) for cs in (pod.status.container_statuses or [])),
            "max_restart_count": max_restart_count,
            "crash_loop_container": crash_loop_container,
        }

        try:
            field_selector = f"involvedObject.name={pod.metadata.name},involvedObject.kind=Pod"
            evts = core_v1.list_namespaced_event(
                namespace=namespace, field_selector=field_selector
            ).items
        except Exception as exc:  # noqa: BLE001
            logger.debug("Event list failed for pod %s: %s", pod.metadata.name, exc)
            evts = []

        # Sort by last_timestamp descending; keep the 5 most recent.
        evts.sort(
            key=lambda e: (e.last_timestamp or e.event_time or e.metadata.creation_timestamp),
            reverse=True,
        )
        for evt in evts[:5]:
            line = f"{evt.type or '?'} {evt.reason or '?'}: {evt.message or ''}"
            events_summary.append(f"{pod.metadata.name}: {line}")
            if (
                evt.reason == "FailedScheduling"
                and evt.message
                and "nvidia.com/gpu" in evt.message
                and ("Insufficient" in evt.message or "quota" in evt.message.lower())
            ):
                gpu_quota_failed_scheduling = True

        pod_entry["recent_events"] = [
            f"{evt.type or '?'} {evt.reason or '?'}: {evt.message or ''}" for evt in evts[:5]
        ]
        pods_summary.append(pod_entry)

    return {
        "pods": pods_summary,
        "events": events_summary,
        "gpu_quota_failed_scheduling": gpu_quota_failed_scheduling,
    }


def _summarize_pod_state(diagnostics: dict[str, Any]) -> str:
    pods = diagnostics.get("pods") or []
    if not pods:
        return "Waiting for inference pod to be scheduled…"

    pod = pods[0]
    phase = pod.get("phase", "Unknown")
    containers = pod.get("containers") or []

    if phase == "Pending":
        # Look at recent events to be more specific.
        for evt in pod.get("recent_events", []):
            if "FailedScheduling" in evt and "nvidia.com/gpu" in evt:
                return "Waiting for a compatible node (FailedScheduling: insufficient nvidia.com/gpu)…"
            if "TriggeredScaleUp" in evt or "Provisioning" in evt:
                return "GKE Autopilot is provisioning a node…"
            if "FailedScheduling" in evt:
                return f"Pod stuck Pending: {evt}"
        return "Pod is Pending — waiting for a node…"

    if phase == "Running":
        for state in containers:
            if state.startswith("waiting/ImagePullBackOff") or state.startswith("waiting/ErrImagePull"):
                return f"Image pull failed: {state}"
        if any("running" == c for c in containers):
            return "Inference container is up — loading model…"
        return "Pod Running, container starting…"

    if phase == "Failed":
        return f"Pod Failed: {'; '.join(containers)}"

    return f"Pod phase={phase}: {'; '.join(containers)}"


def _format_quota_error(diagnostics: dict[str, Any]) -> str:
    """Build a clear, actionable message for a GPU-quota scheduling failure."""
    pods = diagnostics.get("pods") or []
    pod_line = ""
    if pods:
        pod = pods[0]
        evt_line = next(
            (e for e in pod.get("recent_events", []) if "FailedScheduling" in e and "nvidia.com/gpu" in e),
            "",
        )
        pod_line = f" Pod {pod.get('name')} reports: {evt_line}"
    return (
        "Pod could not be scheduled — your GCP project has no compatible GPU "
        "quota in this region."
        + pod_line
        + " Request a quota increase at "
        "https://console.cloud.google.com/iam-admin/quotas — filter by "
        "the relevant GPU metric in the cluster region (for example "
        "'NVIDIA L4 GPUs' in us-central1) "
        "and request at least 1. After the increase is granted, delete this "
        "deployment and create a new one."
    )


def _format_timeout_diagnostics(diagnostics: dict[str, Any]) -> str:
    if not diagnostics:
        return "No pod diagnostics were captured before the timeout."

    parts: list[str] = []
    for pod in (diagnostics.get("pods") or [])[:2]:
        parts.append(
            f"Pod {pod.get('name')} phase={pod.get('phase')} "
            f"containers={pod.get('containers')} "
            f"restarts={pod.get('restart_count', 0)}"
        )
        if pod.get("recent_events"):
            parts.append("  Recent events: " + " | ".join(pod["recent_events"]))
    if not parts:
        parts.append("No pods were ever observed for this deployment.")
    return " | ".join(parts)


_CRASH_LOOP_RESTART_THRESHOLD = 3


def _is_persistent_crash_loop(diagnostics: dict[str, Any]) -> bool:
    """Return True when at least one container has crashed several times.

    The threshold is intentionally low (3) — Kubernetes already backs off
    exponentially between restarts, so by the time we see 3 restarts the
    failure has been reproduced ~3 times in a row. Continuing to wait the
    full 30-minute timeout would just delay surfacing the real error to
    the user.
    """
    for pod in diagnostics.get("pods") or []:
        if (
            pod.get("crash_loop_container")
            and (pod.get("max_restart_count") or 0) >= _CRASH_LOOP_RESTART_THRESHOLD
        ):
            return True
    return False


def _format_crashloop_error(core_v1, namespace: str, diagnostics: dict[str, Any]) -> str:
    """Compose a human-readable error message that includes container logs."""
    pods = diagnostics.get("pods") or []
    if not pods:
        return "Container is in CrashLoopBackOff but no pod metadata is available."

    pod = pods[0]
    pod_name = pod.get("name") or "<unknown>"
    container = pod.get("crash_loop_container") or "<unknown>"
    restarts = pod.get("max_restart_count") or 0

    log_excerpt = _fetch_container_logs(
        core_v1=core_v1,
        namespace=namespace,
        pod_name=pod_name,
        container=container,
    )

    parts = [
        f"Container '{container}' in pod '{pod_name}' is in CrashLoopBackOff "
        f"after {restarts} restart(s). The image was pulled successfully but "
        "the process keeps exiting. Most common causes: model architecture "
        "is not supported by the runtime, missing/incorrect CLI args, or "
        "model requires more memory than the pod has."
    ]
    if log_excerpt:
        parts.append(f"Last container log lines:\n{log_excerpt}")
    else:
        parts.append("(Could not retrieve container logs.)")
    return "\n".join(parts)


def _fetch_container_logs(
    *,
    core_v1,
    namespace: str,
    pod_name: str,
    container: str,
    tail_lines: int = 80,
) -> str:
    """Best-effort fetch of the most recent container logs.

    Tries the previous (crashed) container first via ``previous=True`` since
    the *current* container in CrashLoopBackOff hasn't started yet. Falls
    back to the live container if that fails.
    """
    from kubernetes.client.exceptions import ApiException

    for previous_flag in (True, False):
        try:
            text = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous_flag,
            )
        except ApiException as exc:
            logger.debug(
                "read_namespaced_pod_log(previous=%s) failed for %s/%s: %s",
                previous_flag, pod_name, container, exc,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("Unexpected error fetching logs: %s", exc)
            continue
        if text:
            return text.strip()
    return ""


async def get_service_lb_ip(
    kubeconfig_yaml: str,
    service_name: str,
    namespace: str = "default",
    timeout_seconds: int = 900,
) -> str:
    loop = asyncio.get_event_loop()

    def _wait_for_ip() -> str:
        from kubernetes import client, config

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
            tmp.write(kubeconfig_yaml)
            kubeconfig_path = tmp.name

        try:
            config.load_kube_config(config_file=kubeconfig_path)
            core_v1 = client.CoreV1Api()
            import time
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                svc = core_v1.read_namespaced_service(name=service_name, namespace=namespace)
                ingress = (
                    svc.status
                    and svc.status.load_balancer
                    and svc.status.load_balancer.ingress
                )
                if ingress:
                    ip = ingress[0].ip or ingress[0].hostname
                    if ip:
                        return ip
                time.sleep(5)
            raise TimeoutError(
                f"Service {service_name} never received a LoadBalancer IP within {timeout_seconds}s."
            )
        finally:
            Path(kubeconfig_path).unlink(missing_ok=True)

    return await loop.run_in_executor(None, _wait_for_ip)


async def delete_manifest_objects(kubeconfig_yaml: str, manifest_yaml: str) -> None:
    """Best-effort delete of Secret/Deployment/Service objects for teardown."""
    loop = asyncio.get_event_loop()

    def _delete() -> None:
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
            tmp.write(kubeconfig_yaml)
            kubeconfig_path = tmp.name

        try:
            config.load_kube_config(config_file=kubeconfig_path)
            core_v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()

            for doc in yaml.safe_load_all(manifest_yaml):
                if doc is None:
                    continue
                namespace = doc["metadata"].get("namespace", "default")
                name = doc["metadata"]["name"]
                kind = doc["kind"]

                try:
                    if kind == "Deployment":
                        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace)
                    elif kind == "Service":
                        core_v1.delete_namespaced_service(name=name, namespace=namespace)
                    elif kind == "Secret":
                        core_v1.delete_namespaced_secret(name=name, namespace=namespace)
                except ApiException as exc:
                    if exc.status == 404:
                        continue
                    raise
        finally:
            Path(kubeconfig_path).unlink(missing_ok=True)

    await loop.run_in_executor(None, _delete)


__all__ = [
    "apply_objects",
    "wait_deployment_available",
    "get_service_lb_ip",
    "delete_manifest_objects",
]
