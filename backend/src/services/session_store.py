from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any

INACTIVITY_TIMEOUT_SECONDS = 24 * 60 * 60


class SessionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SessionContext:
    session_token: str
    username: str
    hf_token: str
    issued_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    status: str


@dataclass
class IdempotencyRecord:
    request_fingerprint: str
    status_code: int
    response_body: dict[str, Any]
    updated_at: datetime


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyRecord] = {}

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _build_expiry(self, current: datetime) -> datetime:
        return current + timedelta(seconds=INACTIVITY_TIMEOUT_SECONDS)

    def create_session(self, username: str, hf_token: str) -> SessionContext:
        now = self._now()
        session = SessionContext(
            session_token=token_urlsafe(32),
            username=username,
            hf_token=hf_token,
            issued_at=now,
            last_seen_at=now,
            expires_at=self._build_expiry(now),
            status="active",
        )
        self._sessions[session.session_token] = session
        return session

    def validate_and_touch(self, session_token: str) -> SessionContext:
        session = self._sessions.get(session_token)
        if session is None:
            raise SessionError("missing", "Session not found. Please sign in again.")
        if session.status == "revoked":
            raise SessionError("revoked", "Session has been revoked. Please sign in again.")

        now = self._now()
        if now > session.expires_at:
            session.status = "expired"
            self._sessions[session_token] = session
            raise SessionError("expired", "Session expired. Please sign in again.")

        session.last_seen_at = now
        session.expires_at = self._build_expiry(now)
        self._sessions[session_token] = session
        return session

    def revoke(self, session_token: str) -> None:
        session = self._sessions.get(session_token)
        if session is None:
            raise SessionError("missing", "Session not found. Please sign in again.")
        session.status = "revoked"
        self._sessions[session_token] = session

    def check_idempotency(
        self,
        username: str,
        operation_type: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> IdempotencyRecord | None:
        if not idempotency_key:
            return None
        key = (username, operation_type, idempotency_key)
        existing = self._idempotency.get(key)
        if existing is None:
            return None
        if existing.request_fingerprint != request_fingerprint:
            raise SessionError(
                "idempotency_conflict",
                "Idempotency key reuse with different payload is not allowed.",
            )
        return existing

    def store_idempotency_result(
        self,
        username: str,
        operation_type: str,
        idempotency_key: str | None,
        request_fingerprint: str,
        status_code: int,
        response_body: dict[str, Any],
    ) -> None:
        if not idempotency_key:
            return
        key = (username, operation_type, idempotency_key)
        self._idempotency[key] = IdempotencyRecord(
            request_fingerprint=request_fingerprint,
            status_code=status_code,
            response_body=response_body,
            updated_at=self._now(),
        )


session_store = InMemorySessionStore()
