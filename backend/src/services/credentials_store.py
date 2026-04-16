from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from ..db import get_session_factory
from ..db.models import GCPCredentialsRow
from .crypto import decrypt, encrypt
from .gcp_provider import GCPProvider, GCPProviderError


_NON_TERMINAL_STATUSES = ("queued", "deploying", "running", "deleting")


@dataclass(frozen=True)
class CredentialStatus:
    configured: bool
    service_account_email: str | None
    gcp_project_id_of_sa: str | None
    billing_account_id: str | None
    validation_status: str | None
    validation_error_message: str | None
    last_validated_at: datetime | None


class CredentialsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CredentialsStore:
    """Persistence-layer service for per-user GCP credentials.

    All methods are synchronous wrt SQLAlchemy; callers that live in the async
    request path use `await asyncio.to_thread(...)` only when they also need to
    call the provider, which is already async. DB work stays cheap.
    """

    # ------------------------------------------------------------------ #
    # write path                                                         #
    # ------------------------------------------------------------------ #
    async def save(
        self,
        *,
        user_id: str,
        sa_json: str,
        billing_account_id: str,
        provider: GCPProvider,
    ) -> CredentialStatus:
        result = await provider.validate_credentials(sa_json, billing_account_id)

        encrypted_blob = encrypt(sa_json)
        now = datetime.now(UTC)

        session_factory = get_session_factory()
        with session_factory() as db:
            existing = db.execute(
                select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
            ).scalar_one_or_none()

            if existing is None:
                row = GCPCredentialsRow(
                    user_id=user_id,
                    service_account_json_encrypted=encrypted_blob,
                    billing_account_id=result.billing_account_id,
                    service_account_email=result.service_account_email,
                    gcp_project_id_of_sa=result.gcp_project_id_of_sa,
                    last_validated_at=now,
                    validation_status="valid",
                    validation_error_message=None,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                existing.service_account_json_encrypted = encrypted_blob
                existing.billing_account_id = result.billing_account_id
                existing.service_account_email = result.service_account_email
                existing.gcp_project_id_of_sa = result.gcp_project_id_of_sa
                existing.last_validated_at = now
                existing.validation_status = "valid"
                existing.validation_error_message = None
                existing.updated_at = now

            db.commit()

        return await self.get_status(user_id=user_id)

    # ------------------------------------------------------------------ #
    # read path                                                          #
    # ------------------------------------------------------------------ #
    async def get_status(self, *, user_id: str) -> CredentialStatus:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
            ).scalar_one_or_none()

        if row is None:
            return CredentialStatus(
                configured=False,
                service_account_email=None,
                gcp_project_id_of_sa=None,
                billing_account_id=None,
                validation_status=None,
                validation_error_message=None,
                last_validated_at=None,
            )

        return CredentialStatus(
            configured=True,
            service_account_email=row.service_account_email,
            gcp_project_id_of_sa=row.gcp_project_id_of_sa,
            billing_account_id=row.billing_account_id,
            validation_status=row.validation_status,
            validation_error_message=row.validation_error_message,
            last_validated_at=row.last_validated_at,
        )

    async def get_decrypted(self, *, user_id: str) -> tuple[str, str] | None:
        """Return (sa_json, billing_account_id) if configured and still valid."""
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
            ).scalar_one_or_none()

        if row is None:
            return None

        return decrypt(row.service_account_json_encrypted), row.billing_account_id

    # ------------------------------------------------------------------ #
    # delete                                                             #
    # ------------------------------------------------------------------ #
    async def delete(self, *, user_id: str) -> None:
        session_factory = get_session_factory()
        with session_factory() as db:
            from ..db.models import DeploymentRow

            active_count = db.execute(
                select(DeploymentRow).where(
                    DeploymentRow.user_id == user_id,
                    DeploymentRow.status.in_(_NON_TERMINAL_STATUSES),
                )
            ).first()
            if active_count is not None:
                raise CredentialsError(
                    "active_deployments_exist",
                    "Cannot delete credentials while deployments are still running or in-flight. "
                    "Delete those deployments first.",
                )

            row = db.execute(
                select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
            ).scalar_one_or_none()
            if row is None:
                return
            db.delete(row)
            db.commit()

    # ------------------------------------------------------------------ #
    # background-health hook (used by T062a in US4)                      #
    # ------------------------------------------------------------------ #
    async def record_credentials_invalid(self, *, user_id: str, error: GCPProviderError | Exception) -> None:
        """Flip `validation_status='invalid'` when a background provider call
        fails with an auth/permission error. Safe to call when no row exists
        (it becomes a no-op).
        """
        now = datetime.now(UTC)
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.execute(
                select(GCPCredentialsRow).where(GCPCredentialsRow.user_id == user_id)
            ).scalar_one_or_none()
            if row is None:
                return
            row.validation_status = "invalid"
            row.validation_error_message = str(error)
            row.last_validated_at = now
            row.updated_at = now
            db.commit()


credentials_store = CredentialsStore()


__all__ = ["credentials_store", "CredentialsStore", "CredentialStatus", "CredentialsError"]
