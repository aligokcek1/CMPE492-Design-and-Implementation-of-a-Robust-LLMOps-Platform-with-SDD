# Research & Technical Decisions: Session Persistence and Continuity

## 1) Session Persistence Mechanism

**Decision**: Use backend-issued opaque platform session tokens after HF token verification. Store HF token only server-side in an in-memory session registry and persist only the opaque session token on the frontend.

**Rationale**: This removes repeated HF token entry while reducing client-side token exposure. Existing backend APIs already centralize authenticated behavior; replacing raw HF token propagation with session token propagation is the smallest secure change.

**Alternatives considered**:
- Persist raw HF token on the frontend for reuse: rejected due to increased client-side secret exposure risk.
- Re-verify HF token on every request: rejected due to unnecessary latency and poor UX.
- Add persistent DB-backed session store in v1: rejected as out of scope and unnecessary for current scale.

---

## 2) Expiration Policy and Renewal Semantics

**Decision**: Apply 24-hour sliding inactivity expiration with no absolute maximum lifetime cap. Each successful authenticated request refreshes `expires_at` by 24 hours.

**Rationale**: Matches clarified product direction and minimizes re-login friction for active users. Sliding behavior is deterministic, easy to test, and aligns with the desired UX.

**Alternatives considered**:
- Fixed 24-hour expiration from login time: rejected due to frequent forced re-login for active users.
- Sliding plus 7-day or 30-day absolute cap: rejected because clarified requirements explicitly selected no absolute cap.

---

## 3) Multi-Device Scope and Logout Behavior

**Decision**: Sessions are device/browser-scoped. Logout invalidates only the current session token; no explicit global logout is included in this feature.

**Rationale**: Aligns with clarified scope and avoids disrupting active work on other devices. This keeps implementation focused and reduces regression risk.

**Alternatives considered**:
- Single-session-only model: rejected because it would force logouts across devices and hurt usability.
- Global logout in this feature: rejected as explicitly out-of-scope for 006.

---

## 4) Continuity for Accepted Long-Running Operations

**Decision**: Once upload/deploy request authentication succeeds and operation starts, it continues to completion even if the initiating session expires or is logged out afterward.

**Rationale**: Directly satisfies continuity requirements and prevents wasted user time. Operation execution uses auth context captured at acceptance time, so later session state changes do not invalidate in-flight execution.

**Alternatives considered**:
- Cancel operations immediately on session expiry: rejected due to UX and reliability regressions.
- Mixed policy (upload continues, deploy cancels): rejected for inconsistency and added complexity.

---

## 5) Duplicate Prevention During Session Transitions

**Decision**: Add optional idempotency keys to upload/deploy requests. If a client retries after re-login with the same key, backend returns the original terminal/accepted response instead of re-executing.

**Rationale**: Prevents duplicate operations when users retry around session-expired boundaries. Works with existing endpoints without requiring new orchestration infrastructure.

**Alternatives considered**:
- No idempotency support: rejected because retries can trigger duplicate upload/deploy execution.
- Heavy job queue with exactly-once semantics: rejected as over-engineering for current scope.

---

## 6) Smooth Re-Login UX

**Decision**: Frontend performs session restore check on startup; on 401/session-expired responses, it presents a direct re-login path, preserves local UI context, and retries at most once for safe/read operations.

**Rationale**: Keeps user flow uninterrupted and predictable while avoiding hidden repeated retries for side-effect actions.

**Alternatives considered**:
- Hard redirect to login with full state loss: rejected due to poor UX.
- Unlimited auto-retry loops: rejected due to potential repeated failures and duplicate side effects.
