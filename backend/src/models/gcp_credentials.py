from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


_BILLING_PATTERN = r"^billingAccounts/[A-Z0-9-]{20}$"


class GCPCredentialsRequest(BaseModel):
    service_account_json: str = Field(..., description="Raw JSON contents of the GCP SA key.")
    billing_account_id: str = Field(..., pattern=_BILLING_PATTERN)


class GCPCredentialsStatus(BaseModel):
    configured: bool
    service_account_email: str | None = None
    gcp_project_id_of_sa: str | None = None
    billing_account_id: str | None = None
    validation_status: str | None = None
    validation_error_message: str | None = None
    last_validated_at: datetime | None = None


__all__ = ["GCPCredentialsRequest", "GCPCredentialsStatus"]
