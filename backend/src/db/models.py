from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


def _now() -> datetime:
    return datetime.now(UTC)


VALIDATION_STATUSES = ("valid", "invalid")
DEPLOYMENT_STATUSES = (
    "queued",
    "deploying",
    "running",
    "failed",
    "deleting",
    "deleted",
    "lost",
)


class GCPCredentialsRow(Base):
    __tablename__ = "gcp_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_gcp_credentials_user_id"),
        CheckConstraint(
            f"validation_status IN {VALIDATION_STATUSES}",
            name="ck_gcp_credentials_validation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service_account_json_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    billing_account_id: Mapped[str] = mapped_column(String, nullable=False)
    service_account_email: Mapped[str] = mapped_column(String, nullable=False)
    gcp_project_id_of_sa: Mapped[str] = mapped_column(String, nullable=False)
    last_validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    validation_status: Mapped[str] = mapped_column(String, nullable=False, default="valid")
    validation_error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class DeploymentRow(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        CheckConstraint(
            f"status IN {DEPLOYMENT_STATUSES}",
            name="ck_deployments_status",
        ),
        Index("ix_deployments_user_id", "user_id"),
        Index("ix_deployments_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    hf_model_id: Mapped[str] = mapped_column(String, nullable=False)
    hf_model_display_name: Mapped[str] = mapped_column(String, nullable=False)
    gcp_project_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    gke_cluster_name: Mapped[str] = mapped_column(String, nullable=False)
    gke_region: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    status_message: Mapped[str | None] = mapped_column(String, nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "GCPCredentialsRow",
    "DeploymentRow",
    "VALIDATION_STATUSES",
    "DEPLOYMENT_STATUSES",
]
