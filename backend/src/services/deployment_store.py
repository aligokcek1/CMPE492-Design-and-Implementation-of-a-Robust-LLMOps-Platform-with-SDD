from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from ..db import get_session_factory
from ..db.models import DeploymentRow

_DEFAULT_CLUSTER_NAME = "llmops-cluster"
_DEFAULT_REGION = "us-central1"
_MAX_CONCURRENT_PER_USER = 3
_NON_TERMINAL_STATUSES = ("queued", "deploying", "running", "deleting")


def _allocate_gcp_project_id(deployment_id: str) -> str:
    """Deterministic, unique, GCP-valid project id for this deployment.

    GCP project ids must be 6–30 chars, lowercase letters/digits/hyphens, and
    must start with a letter. Our convention: ``llmops-<8hex>-<6hex>``.
    """
    stripped = deployment_id.replace("-", "")
    return f"llmops-{stripped[:8]}-{stripped[8:14]}"


class DeploymentError(Exception):
    def __init__(self, code: str, message: str, require_confirmation: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.require_confirmation = require_confirmation


class DeploymentStore:
    # ------------------------------------------------------------------ #
    # writes                                                             #
    # ------------------------------------------------------------------ #
    def create(
        self,
        *,
        user_id: str,
        hf_model_id: str,
        hf_model_display_name: str | None = None,
        force: bool = False,
    ) -> DeploymentRow:
        session_factory = get_session_factory()
        with session_factory() as db:
            # 3-deployment cap (FR-013)
            active = db.execute(
                select(DeploymentRow).where(
                    DeploymentRow.user_id == user_id,
                    DeploymentRow.status.in_(_NON_TERMINAL_STATUSES),
                )
            ).scalars().all()
            if len(active) >= _MAX_CONCURRENT_PER_USER:
                raise DeploymentError(
                    "concurrent_deployment_limit",
                    f"You already have {len(active)} active deployments (limit is "
                    f"{_MAX_CONCURRENT_PER_USER}). Delete an existing deployment first.",
                )

            # Duplicate-model confirmation (FR-016)
            if not force:
                has_same_model = db.execute(
                    select(DeploymentRow).where(
                        DeploymentRow.user_id == user_id,
                        DeploymentRow.hf_model_id == hf_model_id,
                        DeploymentRow.status.in_(_NON_TERMINAL_STATUSES),
                    )
                ).first()
                if has_same_model is not None:
                    raise DeploymentError(
                        "duplicate_model_requires_confirmation",
                        f"You already have a deployment of '{hf_model_id}'. Submit again with "
                        "force=true to create a second one.",
                        require_confirmation=True,
                    )

            now = datetime.now(UTC)
            deployment_id = str(uuid.uuid4())
            # Retry a few times on the astronomically-unlikely case of a collision
            for attempt in range(3):
                project_id = _allocate_gcp_project_id(deployment_id)
                if attempt > 0:
                    project_id = f"{project_id}-{secrets.token_hex(1)}"
                exists = db.execute(
                    select(DeploymentRow).where(DeploymentRow.gcp_project_id == project_id)
                ).first()
                if exists is None:
                    break
            else:
                raise DeploymentError(
                    "project_id_collision",
                    "Could not allocate a unique GCP project id. Please retry.",
                )

            row = DeploymentRow(
                id=deployment_id,
                user_id=user_id,
                hf_model_id=hf_model_id,
                hf_model_display_name=hf_model_display_name or hf_model_id.split("/")[-1],
                gcp_project_id=project_id,
                gke_cluster_name=_DEFAULT_CLUSTER_NAME,
                gke_region=_DEFAULT_REGION,
                status="queued",
                status_message="Queued for deployment.",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    def update_status(
        self,
        *,
        deployment_id: str,
        status: str,
        status_message: str | None = None,
        endpoint_url: str | None = None,
        deleted_at: datetime | None = None,
    ) -> DeploymentRow | None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentRow).where(DeploymentRow.id == deployment_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            if status_message is not None:
                row.status_message = status_message
            if endpoint_url is not None:
                row.endpoint_url = endpoint_url
            if deleted_at is not None:
                row.deleted_at = deleted_at
            row.updated_at = datetime.now(UTC)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    # ------------------------------------------------------------------ #
    # reads                                                              #
    # ------------------------------------------------------------------ #
    def get(self, deployment_id: str) -> DeploymentRow | None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentRow).where(DeploymentRow.id == deployment_id)
            ).scalar_one_or_none()
            if row is not None:
                db.expunge(row)
            return row

    def list_by_user(self, user_id: str, include_deleted: bool = False) -> list[DeploymentRow]:
        session_factory = get_session_factory()
        with session_factory() as db:
            stmt = select(DeploymentRow).where(DeploymentRow.user_id == user_id)
            if not include_deleted:
                stmt = stmt.where(DeploymentRow.status != "deleted")
            rows = list(db.execute(stmt.order_by(DeploymentRow.created_at.desc())).scalars().all())
            for row in rows:
                db.expunge(row)
            return rows

    def count_active(self, user_id: str) -> int:
        session_factory = get_session_factory()
        with session_factory() as db:
            return len(db.execute(
                select(DeploymentRow).where(
                    DeploymentRow.user_id == user_id,
                    DeploymentRow.status.in_(_NON_TERMINAL_STATUSES),
                )
            ).scalars().all())

    def list_needing_status_refresh(self) -> list[DeploymentRow]:
        session_factory = get_session_factory()
        with session_factory() as db:
            rows = list(db.execute(
                select(DeploymentRow).where(
                    DeploymentRow.status.in_(("running", "deploying"))
                )
            ).scalars().all())
            for row in rows:
                db.expunge(row)
            return rows

    def hard_delete(self, deployment_id: str) -> None:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(DeploymentRow).where(DeploymentRow.id == deployment_id)
            ).scalar_one_or_none()
            if row is None:
                return
            db.delete(row)
            db.commit()


deployment_store = DeploymentStore()


__all__ = [
    "deployment_store",
    "DeploymentStore",
    "DeploymentError",
    "_MAX_CONCURRENT_PER_USER",
]
