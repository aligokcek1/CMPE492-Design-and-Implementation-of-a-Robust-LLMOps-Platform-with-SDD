from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


_BILLING_PATTERN = r"^billingAccounts/[A-Z0-9-]{20}$"
# Either `organizations/<digits>` or `folders/<digits>`. Empty/None means
# unset — accepted so personal-account users who create projects without a
# parent can still save credentials. The error will surface at deploy-time
# with a clear message if the SA actually requires one.
_PARENT_PATTERN = r"^(organizations|folders)/[0-9]+$"


class GCPCredentialsRequest(BaseModel):
    service_account_json: str = Field(..., description="Raw JSON contents of the GCP SA key.")
    billing_account_id: str = Field(..., pattern=_BILLING_PATTERN)
    gcp_parent: str | None = Field(
        default=None,
        description=(
            "Optional Organization or Folder under which new deployment projects will be "
            "created. Required when creating projects with a service account. Format: "
            "'organizations/<NUMERIC-ID>' or 'folders/<NUMERIC-ID>'."
        ),
        pattern=_PARENT_PATTERN,
    )


class GCPCredentialsStatus(BaseModel):
    configured: bool
    service_account_email: str | None = None
    gcp_project_id_of_sa: str | None = None
    billing_account_id: str | None = None
    gcp_parent: str | None = None
    validation_status: str | None = None
    validation_error_message: str | None = None
    last_validated_at: datetime | None = None


__all__ = ["GCPCredentialsRequest", "GCPCredentialsStatus"]
