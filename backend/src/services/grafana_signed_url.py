"""HMAC-signed Grafana deep link minting and validation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import UTC, datetime, timedelta

from ..models.metrics import GrafanaLinkResponse


class GrafanaSignedUrlError(Exception):
    pass


class GrafanaSignedUrlService:
    def __init__(
        self,
        *,
        signing_secret: str | None = None,
        ttl_seconds: int | None = None,
        grafana_url: str | None = None,
        backend_public_url: str | None = None,
    ) -> None:
        secret = signing_secret or os.environ.get("LLMOPS_GRAFANA_SIGNING_SECRET", "")
        if not secret:
            secret = "dev-only-signing-secret-change-me"
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds or int(os.environ.get("LLMOPS_GRAFANA_LINK_TTL_SECONDS", "900"))
        self._grafana_url = (grafana_url or os.environ.get("LLMOPS_GRAFANA_URL", "http://localhost:3000")).rstrip("/")
        self._backend_public_url = (
            backend_public_url or os.environ.get("LLMOPS_BACKEND_PUBLIC_URL", "http://localhost:8000")
        ).rstrip("/")

    def mint(
        self,
        *,
        deployment_id: str,
        user_id: str,
        dashboard_uid: str,
    ) -> GrafanaLinkResponse:
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        exp = int(expires_at.timestamp())
        payload = f"{deployment_id}|{user_id}|{dashboard_uid}|{exp}"
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        token = base64.urlsafe_b64encode(f"{payload}|{sig}".encode("utf-8")).decode("ascii")
        redirect_url = f"{self._backend_public_url}/api/metrics/grafana/redirect?token={token}"
        return GrafanaLinkResponse(redirect_url=redirect_url, expires_at=expires_at)

    def validate(self, token: str) -> tuple[str, str, str]:
        try:
            decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
            deployment_id, user_id, dashboard_uid, exp_str, sig = decoded.rsplit("|", 4)
            payload = f"{deployment_id}|{user_id}|{dashboard_uid}|{exp_str}"
            expected = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                raise GrafanaSignedUrlError("Invalid token signature")
            if int(exp_str) < int(time.time()):
                raise GrafanaSignedUrlError("Token expired")
        except GrafanaSignedUrlError:
            raise
        except Exception as exc:
            raise GrafanaSignedUrlError("Malformed token") from exc
        return deployment_id, user_id, dashboard_uid

    def grafana_dashboard_url(
        self,
        dashboard_uid: str,
        *,
        deployment_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        url = f"{self._grafana_url}/d/{dashboard_uid}"
        if deployment_id and user_id:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode({'var-deployment_id': deployment_id, 'var-user_id': user_id})}"
        return url


grafana_signed_url_service = GrafanaSignedUrlService()

__all__ = [
    "GrafanaSignedUrlService",
    "GrafanaSignedUrlError",
    "grafana_signed_url_service",
]
