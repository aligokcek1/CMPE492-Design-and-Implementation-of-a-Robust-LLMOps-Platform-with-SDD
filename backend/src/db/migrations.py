from __future__ import annotations

from . import Base, get_engine
from . import models as _models  # noqa: F401 - ensures tables are registered on Base.metadata


def ensure_schema() -> None:
    """Create all tables if they don't already exist (idempotent)."""
    Base.metadata.create_all(bind=get_engine())


__all__ = ["ensure_schema"]
