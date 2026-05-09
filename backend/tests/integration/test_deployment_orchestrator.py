"""T030 + T031 + T047 + T056 — deployment orchestrator state-machine tests.

All of these share the same test file per the plan, which is why T031/T047/T056
are NOT flagged ``[P]`` in tasks.md — they must be appended sequentially here
to avoid merge conflicts.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _seed_credentials(user_id: str = "alice") -> None:
    from src.db import get_session_factory
    from src.db.models import GCPCredentialsRow

    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(GCPCredentialsRow(
            user_id=user_id,
            service_account_json_encrypted=b"not-real-encrypted",
            billing_account_id="billingAccounts/ABCDEF-012345-67890X",
            service_account_email="sa@example.iam.gserviceaccount.com",
            gcp_project_id_of_sa="sa-parent",
            last_validated_at=datetime.now(UTC),
            validation_status="valid",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()


async def _run_orchestrator(deployment_id: str, provider) -> None:
    from src.services.deployment_orchestrator import deployment_orchestrator

    await deployment_orchestrator.run_to_terminal(deployment_id=deployment_id, provider=provider)


def _fetch_row(deployment_id: str):
    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    session_factory = get_session_factory()
    with session_factory() as db:
        return db.execute(select(DeploymentRow).where(DeploymentRow.id == deployment_id)).scalar_one()


def _create_queued_row(user_id: str, model_id: str, project_id: str | None = None) -> str:
    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id=user_id,
            hf_model_id=model_id,
            hf_model_display_name=model_id.split("/")[-1],
            gcp_project_id=project_id or f"llmops-{dep_id.replace('-', '')[:8]}-{dep_id.replace('-', '')[8:14]}",
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="queued",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()
    return dep_id


# --------------------------------------------------------------------------- #
# T030 — happy-path state machine                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_orchestrator_happy_path_reaches_running(temp_db, fake_gcp_provider):
    _seed_credentials("alice")
    dep_id = _create_queued_row("alice", "Qwen/Qwen3-1.7B")

    await _run_orchestrator(dep_id, fake_gcp_provider)

    row = _fetch_row(dep_id)
    assert row.status == "running"
    assert row.endpoint_url is not None
    assert row.endpoint_url.startswith("http://")

    # Inspect the fake provider call history — every required step ran.
    called_methods = [entry[0] for entry in fake_gcp_provider.calls]
    assert "create_project" in called_methods
    assert "enable_services" in called_methods
    assert "attach_billing" in called_methods
    assert "create_gke_cluster" in called_methods
    assert "get_kube_config" in called_methods


# --------------------------------------------------------------------------- #
# T031 — failure path with partial-resources cleanup                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_orchestrator_failure_path_rolls_back_partial_resources(temp_db, fake_gcp_provider):
    _seed_credentials("alice")
    dep_id = _create_queued_row("alice", "Qwen/Qwen3-1.7B")

    from src.services.gcp_fake_provider import GCPQuotaError

    # Let project creation + services succeed, then blow up on cluster create.
    fake_gcp_provider.fail_on("create_gke_cluster", GCPQuotaError("GPU quota exceeded"))

    await _run_orchestrator(dep_id, fake_gcp_provider)

    row = _fetch_row(dep_id)
    assert row.status == "failed"
    assert row.status_message is not None
    assert "quota" in row.status_message.lower() or "exceeded" in row.status_message.lower()

    # Cleanup MUST have torn down the project we partially built.
    called = [entry[0] for entry in fake_gcp_provider.calls]
    assert called.count("delete_project") >= 1


# --------------------------------------------------------------------------- #
# T047 — status-refresh flips to `lost` when project missing                   #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_status_refresh_marks_running_deployment_as_lost_when_project_gone(
    temp_db, fake_gcp_provider,
):
    _seed_credentials("alice")

    # Create a row in `running` state that the fake provider does NOT know about.
    from src.db import get_session_factory
    from src.db.models import DeploymentRow

    dep_id = str(uuid.uuid4())
    project_id = "llmops-ghost01-abcdef"
    session_factory = get_session_factory()
    with session_factory() as db:
        db.add(DeploymentRow(
            id=dep_id,
            user_id="alice",
            hf_model_id="Qwen/Qwen3-1.7B",
            hf_model_display_name="Qwen3 1.7B",
            gcp_project_id=project_id,
            gke_cluster_name="llmops-cluster",
            gke_region="us-central1",
            status="running",
            endpoint_url="http://1.2.3.4:80",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ))
        db.commit()

    from src.services.deployment_orchestrator import deployment_orchestrator

    await deployment_orchestrator.refresh_statuses(provider=fake_gcp_provider)

    row = _fetch_row(dep_id)
    assert row.status == "lost"
    assert row.status_message is not None
    assert "no longer exists" in row.status_message.lower() or "deleted" in row.status_message.lower()


# --------------------------------------------------------------------------- #
# T056 — delete-in-progress cancels orchestrator and transitions to deleted    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_delete_during_deploy_transitions_through_deleting_to_deleted(
    temp_db, fake_gcp_provider,
):
    _seed_credentials("alice")
    dep_id = _create_queued_row("alice", "Qwen/Qwen3-1.7B")

    # Slow down the fake so we can catch the deploy in-flight.
    fake_gcp_provider.artificial_latency_seconds = 0.05

    from src.services.deployment_orchestrator import deployment_orchestrator

    # Using schedule() (instead of raw asyncio.create_task) mirrors what the
    # real route does and, crucially, registers the task so request_deletion
    # can cancel it.
    deployment_orchestrator.schedule(deployment_id=dep_id, provider=fake_gcp_provider)

    # Give the orchestrator time to at least create the project.
    await asyncio.sleep(0.1)

    await deployment_orchestrator.request_deletion(
        deployment_id=dep_id,
        provider=fake_gcp_provider,
    )

    row = _fetch_row(dep_id)
    assert row.status == "deleted"
    assert row.deleted_at is not None
    # delete_project should have been called at least once
    assert any(name == "delete_project" for name, _, _ in fake_gcp_provider.calls)
