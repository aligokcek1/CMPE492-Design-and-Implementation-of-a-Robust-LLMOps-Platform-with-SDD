# Implementation Plan: Session Persistence and Continuity

**Branch**: `006-session-persistence` | **Date**: 2026-04-12 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/006-session-persistence/spec.md`

## Summary

Introduce backend-managed, device-scoped authenticated sessions with 24-hour sliding inactivity expiration (no absolute lifetime cap), so users do not repeatedly enter Hugging Face tokens. The backend will issue an opaque platform session token after HF token verification, and all protected routes will authenticate through this session token. Long-running upload/deploy operations will remain valid after acceptance even if the session ends later, and idempotency keys will prevent duplicate execution during re-login/retry flows.

## Technical Context

**Language/Version**: Python 3.11 (backend + frontend)  
**Primary Dependencies**: FastAPI 0.135, Pydantic 2.12, huggingface_hub 1.7, Streamlit 1.55, pytest, pytest-asyncio, httpx  
**Storage**: In-memory backend session registry (process-local) + browser cookie/local persisted session token for Streamlit client continuity; no database  
**Testing**: Backend contract tests (`pytest`, `pytest-asyncio`, `httpx`), frontend integration tests (`pytest`, `streamlit.testing.v1`)  
**Target Platform**: Local macOS development and Linux deployment for backend/frontend services  
**Project Type**: Web application (FastAPI backend + Streamlit frontend)  
**Performance Goals**: Auth/session validation adds no more than 150 ms p95 overhead per protected request in local integration testing; re-login recovery completes in under 30 seconds for normal workflows  
**Constraints**: 24-hour sliding inactivity window, no absolute session cap, device/browser-scoped sessions, current-device logout only, no disruption to accepted upload/deploy operations  
**Scale/Scope**: Small-to-medium interactive usage (tens to low hundreds of concurrent active sessions), single backend process scope for v1

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Clean & Readable Code | ✅ Pass | Session logic centralized in dedicated auth/session helpers; avoid duplicated token parsing across endpoints |
| II. Security First | ✅ Pass | Opaque session token, no HF token logging, server-side token custody, explicit session invalidation, clear expired-session handling |
| III. Direct Framework & Library Usage | ✅ Pass | Uses FastAPI dependency injection and existing Streamlit/FastAPI primitives directly without unnecessary abstraction layers |
| IV. TDD Mandatory | ✅ Pass | Contract and integration tests defined first for session lifecycle, renewal, expiration, logout, retry, and idempotency |
| V. Realistic & Comprehensive Testing | ✅ Pass | End-to-end request flows cover auth, upload, deploy continuity, and recovery behavior through actual API boundaries |
| VI. Simplicity & Root Cause Resolution | ✅ Pass | Replace repeated Bearer HF-token parsing with one session-based auth path; minimal surface-area changes across existing routes |

**Post-Design Gate Re-check**: ✅ Pass. Phase 1 artifacts keep scope limited to session lifecycle, auth propagation, and continuity safeguards without introducing new infrastructure.

## Project Structure

### Documentation (this feature)

```text
specs/006-session-persistence/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.yml
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── api/
│   │   ├── auth.py                # issue, renew, and revoke platform sessions
│   │   ├── models.py              # switch auth dependency from HF token to session token
│   │   ├── upload.py              # session auth + idempotency support for upload
│   │   └── deployment.py          # session auth + idempotency support for deploy
│   ├── models/
│   │   └── auth.py                # session request/response and session state models
│   └── services/
│       ├── huggingface.py         # unchanged HF operations; consumes token from session context
│       └── session_store.py       # new in-memory session lifecycle service
└── tests/
    └── contract/
        ├── test_auth_api.py        # add session issue/renew/logout tests
        ├── test_upload_api.py      # add operation continuity + idempotency tests
        ├── test_deployment_api.py  # add operation continuity + idempotency tests
        └── test_models_api.py      # verify session-based auth behavior

frontend/
├── src/
│   ├── app.py                      # bootstrap auth restoration and smooth re-login flow
│   ├── components/
│   │   └── auth.py                 # login UI backed by session token issue
│   └── services/
│       ├── api_client.py           # session auth headers, renew/logout calls, retry hook
│       └── session_client.py       # browser persistence helper for session token metadata
└── tests/
    └── integration/
        └── test_workflow.py        # persist login, expiry recovery, upload/deploy continuity
```

**Structure Decision**: Existing web-app split (`backend/` + `frontend/`) is retained. A focused session service is added only where auth state ownership belongs (backend service layer), while frontend receives a small session persistence helper.

---

## Phase 0: Research Findings

See [research.md](./research.md) for detailed rationale and alternatives.

| Decision Area | Resolution |
|---------------|------------|
| Session representation | Backend-issued opaque session token mapped to server-held HF token and session metadata |
| Sliding expiration | 24-hour inactivity renewal on every authenticated request; no absolute max cap |
| Multi-device behavior | Device/browser-scoped independent sessions; current-device logout only |
| Operation continuity | Accepted upload/deploy jobs continue with captured auth context even if session ends |
| Duplicate prevention | Optional idempotency key for upload/deploy endpoints with response replay on retries |

---

## Phase 1: Design

### 1. Authentication and Session Lifecycle

- `POST /api/auth/verify` will validate HF token and return a platform session token plus session metadata.
- `GET /api/auth/session` will validate and refresh (touch) the session inactivity deadline.
- `POST /api/auth/logout` will revoke the current session token only.
- Protected endpoints will consume a shared session dependency that resolves user + HF token context.

### 2. Session Service

Add `backend/src/services/session_store.py`:

- Create session (`session_id`, `user`, `hf_token`, `device_scope`, `issued_at`, `last_seen_at`, `expires_at`, `status`).
- Touch session on each validated request (slide by 24 hours from current activity timestamp).
- Validate/reject expired/revoked sessions.
- Revoke single session on logout.
- Maintain short-term idempotency key map for upload/deploy retries tied to session/user context.

### 3. Endpoint Migration to Session Auth

- Replace per-route `Authorization: Bearer <hf_token>` extraction with shared session-context extraction.
- Keep business logic for model listing/upload/deploy unchanged except auth source.
- Ensure upload/deploy capture required credentials at request acceptance so in-flight operation continues even if session later expires.

### 4. Frontend Session Persistence and Recovery

- Persist platform session token and minimal metadata in browser-backed storage for revisit restoration.
- On app startup: attempt session restore via `GET /api/auth/session`; if valid, repopulate authenticated state seamlessly.
- On expired session: preserve current UI context, show direct re-login prompt, re-authenticate, then continue workflow.
- On logout: clear stored session token and local auth state for current device only.

### 5. Test Plan (TDD order)

1. Backend auth contract tests for issue/renew/expire/logout/device-scoped behavior.
2. Backend upload/deploy contract tests for accepted-operation continuity and idempotent retry behavior.
3. Frontend integration tests for revisit persistence, expired-session recovery UX, and non-duplication on retry.
4. Existing regression contract/integration suites.

---

## Phase 2 Planning Readiness

All major architectural decisions and interface contracts are documented. Task decomposition can proceed directly to `/speckit.tasks`.

## Complexity Tracking

No constitution violations identified; no entries required.
