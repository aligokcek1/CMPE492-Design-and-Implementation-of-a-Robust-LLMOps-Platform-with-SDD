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
HARDWARE_TYPES = ("cpu", "gpu")
DEPLOYMENT_STATUSES = (
    "queued",
    "deploying",
    "running",
    "failed",
    "deleting",
    "deleted",
    "lost",
)
MODEL_ORIGINS = ("uploaded", "public")


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
    # GCP requires service-accounts to create projects under an existing
    # Organization or Folder parent. Format: "organizations/<num>" or
    # "folders/<num>". Nullable for backward compatibility with rows created
    # before the column existed; missing parent → create_project returns a
    # clear 400 at deploy time.
    gcp_parent: Mapped[str | None] = mapped_column(String, nullable=True)
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
        CheckConstraint(
            f"hardware_type IN {HARDWARE_TYPES}",
            name="ck_deployments_hardware_type",
        ),
        CheckConstraint(
            f"model_origin IN {MODEL_ORIGINS}",
            name="ck_deployments_model_origin",
        ),
        Index("ix_deployments_user_id", "user_id"),
        Index("ix_deployments_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    hf_model_id: Mapped[str] = mapped_column(String, nullable=False)
    hf_model_display_name: Mapped[str] = mapped_column(String, nullable=False)
    hardware_type: Mapped[str] = mapped_column(String, nullable=False, default="cpu")
    # GCP/GKE fields — nullable for GPU rows that have no GCP project.
    # SQLite allows multiple NULLs in a UNIQUE column, so the constraint is retained.
    gcp_project_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    gke_cluster_name: Mapped[str | None] = mapped_column(String, nullable=True)
    gke_region: Mapped[str | None] = mapped_column(String, nullable=True)
    # Lightning AI field — null for CPU rows.
    lightning_ai_deployment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model_origin: Mapped[str] = mapped_column(String, nullable=False, default="public")
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    status_message: Mapped[str | None] = mapped_column(String, nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


MONITORING_STATUSES = ("active", "decommissioning")


class DeploymentMonitoringRow(Base):
    __tablename__ = "deployment_monitoring"
    __table_args__ = (
        CheckConstraint(
            f"status IN {MONITORING_STATUSES}",
            name="ck_deployment_monitoring_status",
        ),
        Index("ix_deployment_monitoring_user_id", "user_id"),
    )

    deployment_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    prometheus_scrape_job: Mapped[str] = mapped_column(String, nullable=False)
    grafana_datasource_uid: Mapped[str] = mapped_column(String, nullable=False)
    grafana_dashboard_uid: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    provisioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    decommission_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class LightningAICredentialsRow(Base):
    __tablename__ = "lightning_ai_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_lightning_ai_credentials_user_id"),
        CheckConstraint(
            f"validation_status IN {VALIDATION_STATUSES}",
            name="ck_lightning_ai_credentials_validation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # The Lightning AI platform user UUID (e.g. from LIGHTNING_USER_ID env var).
    # Not a secret — stored plaintext alongside the encrypted api_key.
    lightning_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    validation_status: Mapped[str] = mapped_column(String, nullable=False, default="valid")
    validation_error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    last_validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


__all__ = [
    "GCPCredentialsRow",
    "DeploymentRow",
    "DeploymentMonitoringRow",
    "LightningAICredentialsRow",
    "VALIDATION_STATUSES",
    "HARDWARE_TYPES",
    "DEPLOYMENT_STATUSES",
    "MODEL_ORIGINS",
    "MONITORING_STATUSES",
]
