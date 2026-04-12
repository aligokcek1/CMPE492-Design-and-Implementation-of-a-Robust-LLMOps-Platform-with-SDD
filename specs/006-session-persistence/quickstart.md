# Quickstart: Session Persistence and Continuity

This guide explains how to exercise feature 006 locally once implemented.

## Prerequisites

- Python 3.11+
- Backend and frontend dependencies installed
- Valid Hugging Face token for initial login

## Start Services

```bash
cd backend && uvicorn src.main:app --reload
cd frontend && streamlit run src/app.py
```

## Test-First Workflow

Run tests in Red-Green-Refactor order:

```bash
# 1) Backend contract tests
cd backend && pytest tests/contract/test_auth_api.py tests/contract/test_upload_api.py tests/contract/test_deployment_api.py tests/contract/test_models_api.py

# 2) Frontend integration tests
cd frontend && pytest tests/integration/test_workflow.py
```

## Manual Verification Scenarios

### 1) Initial Login and Session Issue

1. Open the app.
2. Enter HF token and sign in.
3. Confirm authenticated state is shown.
4. Confirm a platform session token is persisted and reused for protected API calls.

Expected outcome:
- Login succeeds once.
- No repeated token prompt during active usage.

### 2) Revisit Persistence (Sliding 24h Inactivity)

1. Sign in and perform any protected action.
2. Close and reopen browser/app within 24h.
3. Verify app restores authenticated state without manual re-login.
4. Continue interacting; verify session inactivity deadline refreshes.

Expected outcome:
- User remains logged in while activity occurs at least once per 24h.

### 3) Expired Session Recovery

1. Simulate session expiry (time-shift or test fixture).
2. Attempt protected action.
3. Confirm clear session-expired prompt.
4. Re-login from prompt and continue workflow.

Expected outcome:
- Recovery path is direct.
- User context (tab/selection/operation view) is preserved.

### 4) Upload/Deploy Continuity After Session End

1. Start upload or deployment request.
2. Invalidate/expire session while operation is in progress.
3. Wait for operation completion.
4. Re-login and inspect resulting status.

Expected outcome:
- Accepted operation reaches terminal state.
- Re-login allows status/result access.

### 5) Retry Without Duplication

1. Trigger upload/deploy with idempotency key.
2. Force session-expired response and retry with same key after re-login.
3. Repeat with same key but different payload.

Expected outcome:
- Same key + same payload returns original result, no duplicate execution.
- Same key + different payload returns conflict.

## API Contract

See `specs/006-session-persistence/contracts/api.yml` for session and idempotency interface details.
