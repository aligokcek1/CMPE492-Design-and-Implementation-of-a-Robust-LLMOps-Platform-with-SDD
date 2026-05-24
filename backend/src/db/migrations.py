from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from . import Base, get_engine
from . import models as _models  # noqa: F401 - ensures tables are registered on Base.metadata

logger = logging.getLogger("llmops.db.migrations")


# ---------------------------------------------------------------------------
# Additive column migrations (simple ALTER TABLE ADD COLUMN)
# ---------------------------------------------------------------------------

_ADD_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("gcp_credentials", "gcp_parent", "ALTER TABLE gcp_credentials ADD COLUMN gcp_parent TEXT"),
    (
        "lightning_ai_credentials",
        "lightning_user_id",
        "ALTER TABLE lightning_ai_credentials ADD COLUMN lightning_user_id TEXT",
    ),
    (
        "deployments",
        "model_origin",
        "ALTER TABLE deployments ADD COLUMN model_origin TEXT NOT NULL DEFAULT 'public'",
    ),
)


def _apply_additive_column_migrations() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    for table_name, column_name, ddl in _ADD_COLUMN_MIGRATIONS:
        if not inspector.has_table(table_name):
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name in existing_cols:
            continue
        logger.info("Applying additive migration: %s", ddl)
        with engine.begin() as conn:
            conn.execute(text(ddl))


# ---------------------------------------------------------------------------
# Structural migration: rebuild `deployments` to make GKE columns nullable
# and add `hardware_type` / `lightning_ai_deployment_id`.
#
# SQLite cannot ALTER COLUMN to drop NOT NULL, so we rebuild within a
# transaction. A failure rolls back completely, leaving the old table intact.
# The rebuild is gated on the absence of `hardware_type` so it runs exactly
# once per existing DB and is a no-op for fresh installs (create_all handles
# fresh installs directly).
# ---------------------------------------------------------------------------

_DEPLOYMENTS_REBUILD_DDL = """
CREATE TABLE deployments_new (
    id                        TEXT     NOT NULL PRIMARY KEY,
    user_id                   TEXT     NOT NULL,
    hf_model_id               TEXT     NOT NULL,
    hf_model_display_name     TEXT     NOT NULL,
    hardware_type             TEXT     NOT NULL DEFAULT 'cpu',
    gcp_project_id            TEXT     UNIQUE,
    gke_cluster_name          TEXT,
    gke_region                TEXT,
    lightning_ai_deployment_id TEXT,
    status                    TEXT     NOT NULL DEFAULT 'queued',
    status_message            TEXT,
    endpoint_url              TEXT,
    created_at                DATETIME NOT NULL,
    updated_at                DATETIME NOT NULL,
    deleted_at                DATETIME
)
"""

_DEPLOYMENTS_COPY_DDL = """
INSERT INTO deployments_new
    (id, user_id, hf_model_id, hf_model_display_name,
     hardware_type, gcp_project_id, gke_cluster_name, gke_region,
     lightning_ai_deployment_id,
     status, status_message, endpoint_url,
     created_at, updated_at, deleted_at)
SELECT
    id, user_id, hf_model_id, hf_model_display_name,
    'cpu',         gcp_project_id, gke_cluster_name, gke_region,
    NULL,
    status, status_message, endpoint_url,
    created_at, updated_at, deleted_at
FROM deployments
"""


def _rebuild_deployments_if_needed() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("deployments"):
        return
    existing_cols = {col["name"] for col in inspector.get_columns("deployments")}
    if "hardware_type" in existing_cols:
        return

    logger.info("Rebuilding `deployments` table to add hardware_type / nullable GKE columns.")
    with engine.begin() as conn:
        conn.execute(text(_DEPLOYMENTS_REBUILD_DDL))
        conn.execute(text(_DEPLOYMENTS_COPY_DDL))
        conn.execute(text("DROP TABLE deployments"))
        conn.execute(text("ALTER TABLE deployments_new RENAME TO deployments"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deployments_user_id ON deployments (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deployments_user_status ON deployments (user_id, status)"))
    logger.info("Deployments table rebuild complete.")


def ensure_schema() -> None:
    """Create missing tables then apply all migrations.

    Execution order:
    1. Structural rebuild of `deployments` (must run BEFORE create_all so
       that the old table is gone before create_all tries to reconcile it).
    2. create_all — handles fresh installs and creates any missing tables
       (including `lightning_ai_credentials`).
    3. Additive column migrations — handles old DBs missing a nullable column.
    """
    _rebuild_deployments_if_needed()
    Base.metadata.create_all(bind=get_engine())
    _apply_additive_column_migrations()
    _ensure_deployment_monitoring_table()


_DEPLOYMENT_MONITORING_DDL = """
CREATE TABLE IF NOT EXISTS deployment_monitoring (
    deployment_id            TEXT     NOT NULL PRIMARY KEY,
    user_id                  TEXT     NOT NULL,
    prometheus_scrape_job    TEXT     NOT NULL,
    grafana_datasource_uid   TEXT     NOT NULL,
    grafana_dashboard_uid    TEXT     NOT NULL,
    status                   TEXT     NOT NULL DEFAULT 'active',
    provisioned_at           DATETIME NOT NULL,
    decommission_at          DATETIME,
    created_at               DATETIME NOT NULL,
    updated_at               DATETIME NOT NULL,
    CHECK (status IN ('active', 'decommissioning'))
)
"""


def _ensure_deployment_monitoring_table() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    if inspector.has_table("deployment_monitoring"):
        return
    logger.info("Creating `deployment_monitoring` table.")
    with engine.begin() as conn:
        conn.execute(text(_DEPLOYMENT_MONITORING_DDL))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_deployment_monitoring_user_id "
            "ON deployment_monitoring (user_id)"
        ))


__all__ = ["ensure_schema"]
