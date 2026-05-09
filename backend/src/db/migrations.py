from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from . import Base, get_engine
from . import models as _models  # noqa: F401 - ensures tables are registered on Base.metadata


logger = logging.getLogger("llmops.db.migrations")


# Column-level migrations keyed by (table_name, column_name) → DDL fragment to add.
# Kept tiny and explicit on purpose — we don't want Alembic for a single-file
# SQLite DB at student-project scale (see plan.md Complexity Tracking).
_ADD_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("gcp_credentials", "gcp_parent", "ALTER TABLE gcp_credentials ADD COLUMN gcp_parent TEXT"),
)


def _apply_additive_column_migrations() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    for table_name, column_name, ddl in _ADD_COLUMN_MIGRATIONS:
        if not inspector.has_table(table_name):
            # Fresh install — create_all below will set the column up correctly.
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name in existing_cols:
            continue
        logger.info("Applying additive migration: %s", ddl)
        with engine.begin() as conn:
            conn.execute(text(ddl))


def ensure_schema() -> None:
    """Create missing tables then apply additive column migrations.

    Order matters: ``create_all`` handles the first-run case (column is
    created as part of the table definition); the additive-migrations pass
    after it handles upgrade-in-place for databases that already had the
    table without the new column.
    """
    Base.metadata.create_all(bind=get_engine())
    _apply_additive_column_migrations()


__all__ = ["ensure_schema"]
