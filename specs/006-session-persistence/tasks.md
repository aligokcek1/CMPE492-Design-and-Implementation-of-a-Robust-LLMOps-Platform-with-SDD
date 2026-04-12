# Tasks: Session Persistence and Continuity

**Input**: Design documents from `/specs/006-session-persistence/`  
**Prerequisites**: `plan.md` (required), `spec.md` (required), `research.md`, `data-model.md`, `contracts/api.yml`, `quickstart.md`

**Tests**: Include test tasks (TDD is explicitly required by constitution and plan).  
**Organization**: Tasks are grouped by user story so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (`[US1]`, `[US2]`, `[US3]`) for story-phase tasks only
- Every task includes exact file path(s)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare shared test scaffolding and request helpers for session-based auth rollout.

- [ ] T001 [P] Add reusable backend session auth test fixtures in `backend/tests/contract/conftest.py`
- [ ] T002 [P] Add frontend session-state test bootstrap helpers in `frontend/conftest.py`
- [ ] T003 [P] Add idempotency-key test helper utilities in `backend/tests/contract/test_upload_api.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build core session primitives and shared auth plumbing required by all stories.

**⚠️ CRITICAL**: No user story implementation starts before this phase is complete.

- [ ] T004 Define session-aware auth request/response models in `backend/src/models/auth.py`
- [ ] T005 Implement in-memory session lifecycle store (`create/validate/touch/revoke`) in `backend/src/services/session_store.py`
- [ ] T006 [P] Add shared session extraction dependency for protected routes in `backend/src/api/auth_helpers.py`
- [ ] T007 Refactor protected route auth dependency usage in `backend/src/api/models.py`, `backend/src/api/upload.py`, and `backend/src/api/deployment.py`
- [ ] T008 [P] Add frontend browser persistence helper for platform session token in `frontend/src/services/session_client.py`
- [ ] T009 Refactor API client to send platform session token headers in `frontend/src/services/api_client.py`

**Checkpoint**: Session primitives and shared auth path are ready for story-level delivery.

---

## Phase 3: User Story 1 - Stay Logged In Across Visits (Priority: P1) 🎯 MVP

**Goal**: Users stay authenticated across revisits with 24-hour sliding inactivity expiration and no absolute cap.

**Independent Test**: Sign in once, revisit within 24 hours without re-login, and verify protected actions still succeed; after inactivity expiry, verify re-login is required.

### Tests for User Story 1 (write first, must fail first) ⚠️

- [ ] T010 [P] [US1] Add contract tests for session issue/renew/logout in `backend/tests/contract/test_auth_api.py`
- [ ] T011 [P] [US1] Add contract tests for protected endpoint behavior with valid vs expired sessions in `backend/tests/contract/test_models_api.py`
- [ ] T012 [P] [US1] Add frontend integration test for revisit persistence without re-login in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 1

- [ ] T013 [US1] Implement session issuance response in `backend/src/api/auth.py`
- [ ] T014 [US1] Implement session validation/renew endpoint in `backend/src/api/auth.py`
- [ ] T015 [US1] Implement current-device logout endpoint in `backend/src/api/auth.py`
- [ ] T016 [US1] Implement 24-hour sliding expiration touch logic and no-cap behavior in `backend/src/services/session_store.py`
- [ ] T017 [US1] Implement login flow storing platform session token in `frontend/src/components/auth.py`
- [ ] T018 [US1] Implement app startup session restore and auth gate in `frontend/src/app.py`
- [ ] T019 [US1] Implement sign-out flow calling backend logout and clearing local session data in `frontend/src/app.py` and `frontend/src/services/api_client.py`

**Checkpoint**: US1 is independently functional and demoable as MVP.

---

## Phase 4: User Story 2 - Keep Long Operations Safe (Priority: P2)

**Goal**: Accepted upload/deploy operations continue to terminal state even if the session later expires or logs out; retries do not create duplicates.

**Independent Test**: Start upload/deploy, expire session mid-flight, confirm operation reaches terminal state, then re-login and verify final status is available with no duplicate execution on retry.

### Tests for User Story 2 (write first, must fail first) ⚠️

- [ ] T020 [P] [US2] Add contract tests for upload continuity and idempotent retries in `backend/tests/contract/test_upload_api.py`
- [ ] T021 [P] [US2] Add contract tests for deployment continuity and idempotent retries in `backend/tests/contract/test_deployment_api.py`
- [ ] T022 [P] [US2] Add frontend integration test for retry-without-duplicate behavior in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 2

- [ ] T023 [US2] Implement operation receipt and idempotency tracking in `backend/src/services/session_store.py`
- [ ] T024 [US2] Add `X-Idempotency-Key` handling and dedupe response replay in `backend/src/api/upload.py`
- [ ] T025 [US2] Add `X-Idempotency-Key` handling and dedupe response replay in `backend/src/api/deployment.py`
- [ ] T026 [US2] Ensure upload operations capture auth context at acceptance and continue after session end in `backend/src/api/upload.py` and `backend/src/services/huggingface.py`
- [ ] T027 [US2] Ensure deployment operations capture auth context at acceptance and continue after session end in `backend/src/api/deployment.py` and `backend/src/services/mock_gcp.py`
- [ ] T028 [US2] Send idempotency keys for upload/deploy requests in `frontend/src/services/api_client.py`, `frontend/src/components/upload.py`, and `frontend/src/components/deploy.py`

**Checkpoint**: US2 is independently functional with continuity and dedupe guarantees.

---

## Phase 5: User Story 3 - Smooth Re-Login and Recovery (Priority: P3)

**Goal**: On session expiry, users get a clear re-login path and resume from equivalent working context with minimal friction.

**Independent Test**: Force session expiration during normal usage, verify clear prompt, complete re-login, and confirm user returns to prior functional context.

### Tests for User Story 3 (write first, must fail first) ⚠️

- [ ] T029 [P] [US3] Add contract tests for explicit session-expired error semantics in `backend/tests/contract/test_auth_api.py` and `backend/tests/contract/test_models_api.py`
- [ ] T030 [P] [US3] Add frontend integration test for expired-session prompt and context recovery in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 3

- [ ] T031 [US3] Standardize expired-session error payloads for protected endpoints in `backend/src/api/auth_helpers.py` and `backend/src/api/errors.py`
- [ ] T032 [US3] Implement pending action/context preservation on auth failures in `frontend/src/app.py`
- [ ] T033 [US3] Implement guided re-login prompt and post-login resume behavior in `frontend/src/components/auth.py` and `frontend/src/app.py`
- [ ] T034 [US3] Implement one-time safe retry policy after re-authentication in `frontend/src/services/api_client.py`

**Checkpoint**: US3 is independently functional with smooth recovery UX.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final consistency pass across stories and verification against contracts/quickstart.

- [ ] T035 [P] Update/align API behavior documentation in `specs/006-session-persistence/contracts/api.yml` and `specs/006-session-persistence/quickstart.md`
- [ ] T036 Run full backend contract suite and fix regressions in `backend/tests/contract/test_auth_api.py`, `backend/tests/contract/test_upload_api.py`, `backend/tests/contract/test_deployment_api.py`, and `backend/tests/contract/test_models_api.py`
- [ ] T037 Run frontend integration suite and fix regressions in `frontend/tests/integration/test_workflow.py`
- [ ] T038 [P] Run lint and cleanup touched backend/frontend files in `backend/src/` and `frontend/src/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (Foundational)**: Depends on Phase 1; blocks all user stories
- **Phase 3 (US1)**: Depends on Phase 2; MVP
- **Phase 4 (US2)**: Depends on Phase 2 and integrates with US1 auth/session path
- **Phase 5 (US3)**: Depends on Phase 2 and uses US1 session lifecycle behavior
- **Phase 6 (Polish)**: Depends on completed target stories

### User Story Dependencies

- **US1 (P1)**: Can start immediately after Foundational phase
- **US2 (P2)**: Requires Foundational; builds on session auth path established in US1
- **US3 (P3)**: Requires Foundational; can run after US1 baseline auth UX exists

### Within Each User Story

- Tests first and failing before implementation
- Backend auth/session behavior before frontend UX wiring
- Endpoint behavior before final integration validation

### Parallel Opportunities

- Phase 1 tasks marked `[P]` can run concurrently
- In Phase 2, T006 and T008 can run in parallel after T004/T005 start
- In each story, `[P]` test tasks can run concurrently
- US2 backend continuity tasks and frontend idempotency client task can be split across developers
- Polish lint/doc tasks can run in parallel with regression triage

---

## Parallel Example: User Story 1

```bash
# Parallel test-first work for US1
Task: "T010 [US1] backend session lifecycle contract tests in backend/tests/contract/test_auth_api.py"
Task: "T011 [US1] protected endpoint session auth tests in backend/tests/contract/test_models_api.py"
Task: "T012 [US1] frontend revisit persistence test in frontend/tests/integration/test_workflow.py"
```

## Parallel Example: User Story 2

```bash
# Parallel backend continuity coverage for US2
Task: "T020 [US2] upload continuity/idempotency tests in backend/tests/contract/test_upload_api.py"
Task: "T021 [US2] deployment continuity/idempotency tests in backend/tests/contract/test_deployment_api.py"
Task: "T022 [US2] frontend retry dedupe test in frontend/tests/integration/test_workflow.py"
```

## Parallel Example: User Story 3

```bash
# Parallel recovery UX validation for US3
Task: "T029 [US3] expired-session API semantics tests in backend/tests/contract/test_auth_api.py and backend/tests/contract/test_models_api.py"
Task: "T030 [US3] expired-session recovery UX test in frontend/tests/integration/test_workflow.py"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 + Phase 2
2. Complete US1 (Phase 3)
3. Validate independent US1 test criteria
4. Demo persistent login behavior

### Incremental Delivery

1. Deliver US1 (persistent sessions)
2. Add US2 (operation continuity + dedupe retries)
3. Add US3 (smooth re-login and context recovery)
4. Finish with cross-cutting validation and polish

### Parallel Team Strategy

1. Team aligns on foundational session interfaces (Phase 2)
2. Split by story after foundation:
   - Engineer A: US1 backend/frontend session lifecycle
   - Engineer B: US2 continuity + idempotency
   - Engineer C: US3 UX recovery and retry orchestration

---

## Notes

- `[P]` tasks are safe to parallelize due to file/dependency separation
- Story labels maintain traceability back to `spec.md` user stories
- Each story phase includes explicit independent test criteria
- Keep Red-Green-Refactor discipline for every test task before implementation
