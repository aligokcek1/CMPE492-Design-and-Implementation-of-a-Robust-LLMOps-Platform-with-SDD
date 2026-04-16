# Tasks: GKE Inference Pipeline for Public HuggingFace Models

**Input**: Design documents from `/specs/007-gke-inference-pipeline/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml, quickstart.md
**TDD**: Mandatory (Constitution Principle IV). Tests are written first and must fail before implementation proceeds.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks). Parallelism is evaluated **within a single phase's execution window** — two `[P]` tasks in different phases touching the same file (e.g. `frontend/src/services/api_client.py` edited once per user story in T025/T043/T051/T064/T071) never collide because phases execute sequentially.
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5)
- Include exact file paths in descriptions

## Path Conventions

Web app layout (existing): `backend/src/`, `backend/tests/`, `frontend/src/`, `frontend/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New dependencies, data directory, env-var convention.

- [ ] T001 Add new dependencies to `backend/requirements.txt`: `sqlalchemy>=2.0`, `cryptography>=42`, `google-cloud-resource-manager>=1.13`, `google-cloud-billing>=1.13`, `google-cloud-container>=2.50`, `google-auth>=2.30`, `kubernetes>=30.0`
- [ ] T002 [P] Create empty data directory `backend/data/.gitkeep` and add `backend/data/*.db*` to `backend/.gitignore`
- [ ] T003 [P] Add `LLMOPS_ENCRYPTION_KEY` env-var generation snippet and note to `backend/README.md` (or create if missing) per `quickstart.md`
- [ ] T004 [P] Add Ruff `extend-exclude = ["data/"]` entry in `backend/pyproject.toml` (or equivalent config) to avoid linting the SQLite DB if present

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB layer, GCPProvider protocol boundary, DI wiring, test fixtures. No user-story work begins until this phase is complete.

**⚠️ CRITICAL**: All user stories depend on this phase.

- [ ] T005 Create SQLAlchemy engine + session factory + declarative base in `backend/src/db/__init__.py`
- [ ] T006 [P] Define ORM models `GCPCredentialsRow` and `DeploymentRow` (columns per `data-model.md`) in `backend/src/db/models.py`
- [ ] T007 [P] Implement `ensure_schema()` using `Base.metadata.create_all` (idempotent) in `backend/src/db/migrations.py`
- [ ] T008 Wire DB init into FastAPI lifespan startup (call `ensure_schema()`) in `backend/src/main.py`
- [ ] T009 [P] Implement Fernet encrypt/decrypt helpers reading `LLMOPS_ENCRYPTION_KEY` in `backend/src/services/crypto.py`
- [ ] T010 [P] Define `GCPProvider` Protocol (methods: `validate_credentials`, `create_project`, `enable_services`, `attach_billing`, `create_gke_cluster`, `get_kube_config`, `delete_project`, `project_exists`) in `backend/src/services/gcp_provider.py`
- [ ] T011 [P] Implement `FakeGCPProvider` (in-memory, async, configurable failures) in `backend/src/services/gcp_fake_provider.py`
- [ ] T012 Wire FastAPI `Depends`-based injection for `GCPProvider` (real by default, fake via override) in `backend/src/main.py`
- [ ] T013 [P] Extend `backend/tests/contract/conftest.py` with per-test temp SQLite file fixture and `GCPProvider` override defaulting to `FakeGCPProvider`
- [ ] T014 [P] Add `NEVER_IMPORT_REAL_GCP_IN_TESTS` import guard test in `backend/tests/contract/test_test_isolation.py` that asserts `google.cloud.*` modules are not loaded when `pytest` runs without opt-in env vars

**Checkpoint**: Foundation ready — user-story implementation can begin.

---

## Phase 3: User Story 1 — Configure GCP Credentials (Priority: P1) 🎯 MVP

**Goal**: A logged-in user can save, validate, view, and delete their GCP service-account key + billing account ID. Credentials persist across backend restarts, encrypted at rest, and are never returned from the API.

**Independent Test**: Start backend, POST a valid SA JSON + billing ID to `/api/gcp/credentials`, verify 200 with status=valid; GET returns the same status without the secret; restart backend, GET still reports `configured: true`.

### Tests for US1 (write first — must FAIL before implementation)

- [ ] T015 [US1] Contract tests for `POST /api/gcp/credentials` (200 save+validate, 400 malformed JSON, 400 validation-fail-not-saved, 401 no session) in `backend/tests/contract/test_gcp_credentials_api.py`
- [ ] T016 [US1] Contract tests for `GET /api/gcp/credentials` (configured=false initial, configured=true post-save, never leaks SA JSON, 401 no session) — same file `backend/tests/contract/test_gcp_credentials_api.py`
- [ ] T017 [US1] Contract tests for `DELETE /api/gcp/credentials` (204 success, 409 when active deployments exist, 401 no session) — same file `backend/tests/contract/test_gcp_credentials_api.py`
- [ ] T018 [P] [US1] Integration test: Fernet round-trip through a real SQLite temp file, verifying the stored blob is NOT plaintext JSON, in `backend/tests/integration/test_credentials_encryption.py`
- [ ] T019 [P] [US1] Frontend integration test: credentials form renders, submits, shows validation badge and error states, in `frontend/tests/integration/test_credentials_workflow.py`

### Implementation for US1

- [ ] T020 [P] [US1] Pydantic request/response models (`GCPCredentialsRequest`, `GCPCredentialsStatus`) per `contracts/openapi.yaml` in `backend/src/models/gcp_credentials.py`
- [ ] T021 [US1] `credentials_store.save`, `.get_status`, `.get_decrypted`, `.delete` with Fernet + SQLAlchemy in `backend/src/services/credentials_store.py` (depends on T009, T020)
- [ ] T022 [US1] Implement `validate_credentials(sa_json, billing_id)` for both `RealGCPProvider` and `FakeGCPProvider` — real impl parses JSON, instantiates `google.auth.credentials`, calls `Projects.list` + `CloudBilling.get_billing_account`; failures map to structured errors. Update `backend/src/services/gcp_provider.py` and `backend/src/services/gcp_fake_provider.py`
- [ ] T023 [US1] Implement `POST`, `GET`, `DELETE /api/gcp/credentials` routes in `backend/src/api/gcp_credentials.py` (uses session-auth dep + credentials_store + GCPProvider)
- [ ] T024 [US1] Register `gcp_credentials` router in `backend/src/main.py`
- [ ] T025 [P] [US1] Add `save_gcp_credentials`, `get_gcp_credentials_status`, `delete_gcp_credentials` methods in `frontend/src/services/api_client.py`
- [ ] T026 [US1] Credentials form component (text-area for SA JSON, text input for billing ID, validation feedback) in `frontend/src/components/gcp_credentials.py`
- [ ] T027 [US1] Add "GCP Credentials" tab wiring in `frontend/src/app.py`

**Checkpoint**: US1 is fully functional. MVP deliverable — user can complete the onboarding flow end-to-end.

---

## Phase 4: User Story 2 — Deploy Public HuggingFace Model to GCP (Priority: P2)

**Goal**: User selects a supported public HF text-generation model → platform creates a dedicated GCP project → brings up a GKE Autopilot cluster on cheapest L4 GPU → deploys vLLM → exposes a LoadBalancer inference endpoint → shows status transitions.

**Independent Test**: With valid credentials saved, POST `/api/deployments` with `hf_model_id=Qwen/Qwen3-1.7B` → receive 202 + `queued` record → observe state machine transition through `deploying` → `running` (using `FakeGCPProvider`, this is deterministic and fast) → endpoint URL populated.

### Tests for US2 (write first — must FAIL before implementation)

- [ ] T028 [US2] Contract tests for `POST /api/deployments` (202 success, 400 unsupported-model-task, 409 cap reached, 409 missing-or-invalid credentials, 409 duplicate model requires confirmation, 202 with `force=true` bypass) in `backend/tests/contract/test_deployment_api.py`
- [ ] T029 [US2] Contract tests for `GET /api/deployments/{id}` (200 with detail incl. project id + console URL, 404 when not owner) — same file `backend/tests/contract/test_deployment_api.py`
- [ ] T030 [P] [US2] Integration test: `deployment_orchestrator` happy-path state machine with `FakeGCPProvider` → asserts `queued→deploying→running` and endpoint URL populated, in `backend/tests/integration/test_deployment_orchestrator.py`
- [ ] T031 [US2] Integration test: orchestrator failure path — fake provider raises during cluster create → deployment transitions to `failed` AND partial resources are torn down, in `backend/tests/integration/test_deployment_orchestrator.py` _(shares file with T030 — not parallel)_
- [ ] T032 [P] [US2] Integration test: vLLM manifest snapshot — `vllm_manifest.generate(...)` produces valid `Deployment + Service + Secret` YAML matching `data-model.md` contract, in `backend/tests/integration/test_vllm_manifest.py`
- [ ] T033 [P] [US2] Opt-in dry-run test: apply generated manifests with `kubernetes.client` `dry_run=["All"]` against a scratch cluster (`LLMOPS_K8S_DRYRUN_KUBECONFIG`); skipped when env var unset, in `backend/tests/dryrun/test_vllm_manifest_dryrun.py`
- [ ] T034 [P] [US2] Frontend integration test: deploy flow with duplicate-model confirmation dialog and progress indicator, in `frontend/tests/integration/test_gke_deploy_workflow.py`

### Implementation for US2

- [ ] T035 [P] [US2] Pydantic models (`DeployRequest`, `Deployment`, `DeploymentDetail`, `DeploymentStatus` enum) in `backend/src/models/deployment.py`
- [ ] T036 [P] [US2] `deployment_store` CRUD (create, get, list-by-user, update-status, count-active-by-user, find-by-user-and-model) in `backend/src/services/deployment_store.py`
- [ ] T037 [P] [US2] HF model gate (`is_supported_text_generation_model`, parse tags + pipeline_tag from HF metadata, reject non-text-gen with clear reason) in `backend/src/services/hf_models.py`
- [ ] T038 [P] [US2] `vllm_manifest.generate(hf_model_id, hf_token_ref, cluster_name)` — returns `Deployment` (1 L4 GPU, `vllm/vllm-openai:latest`), `Service` type=LoadBalancer, `Secret` hf-token — in `backend/src/services/vllm_manifest.py`
- [ ] T039 [P] [US2] `kube_client` helpers (`apply_objects`, `wait_deployment_available`, `get_service_lb_ip`) using official `kubernetes` client in `backend/src/services/kube_client.py`
- [ ] T040 [US2] Extend `GCPProvider` (both Real + Fake): `create_project`, `enable_services`, `attach_billing`, `create_gke_cluster` (Autopilot, `us-central1`), `get_kube_config`. Update `backend/src/services/gcp_provider.py` and `backend/src/services/gcp_fake_provider.py`
- [ ] T041 [US2] `deployment_orchestrator` async state machine: picks up queued rows, drives through project→billing→services→cluster→kubeconfig→manifests→LB-IP, updates DB status at each step, handles rollback on failure. In `backend/src/services/deployment_orchestrator.py`
- [ ] T042 [US2] Implement `POST /api/deployments` (preflight: creds, cap, duplicate-confirm) and `GET /api/deployments/{id}` in `backend/src/api/deployment.py` (keep existing `/api/deployment/mock` personal-repo path untouched per FR-010)
- [ ] T042a [US2] Remove or mark-deprecated the **public-repo** mock deploy path inside `backend/src/api/deployment.py` (personal-repo mock retained per FR-010). Update any prior contract tests (feature 005) that assumed the old public-repo mock path so both mock and real public-repo code do not coexist during Phases 5–7. Also update `frontend/src/components/deploy.py` so the "Deploy public repo" button routes to the new `/api/deployments` flow, while the personal-repo button continues to hit `/api/deployment/mock`.
- [ ] T043 [P] [US2] `api_client.create_deployment`, `get_deployment` in `frontend/src/services/api_client.py`
- [ ] T044 [US2] Deploy button + duplicate-model confirmation dialog + live status display, in `frontend/src/components/deploy.py`

**Checkpoint**: US2 complete. Real deployment flow fully exercised through `FakeGCPProvider` in tests; manual end-to-end on real GCP happens before release per Testing Policy.

---

## Phase 5: User Story 3 — View Active Deployments (Priority: P3)

**Goal**: User sees a list of their deployments with model, status, endpoint URL. List auto-refreshes when statuses change. "Lost" state surfaces when a GCP project is externally deleted.

**Independent Test**: With at least one `running` deployment, GET `/api/deployments` → receive array with correct fields; delete the underlying project via `FakeGCPProvider`; trigger status refresh → list shows deployment with `lost` status.

### Tests for US3 (write first)

- [ ] T045 [US3] Contract tests for `GET /api/deployments` (200 with caller-only rows, never leaks other users', 401 no session) in `backend/tests/contract/test_deployment_api.py`
- [ ] T046 [US3] Contract test for `GET /api/deployments/{id}` 404 when not owner — same file `backend/tests/contract/test_deployment_api.py`
- [ ] T047 [US3] Integration test: status-refresh job transitions a deployment to `lost` when `FakeGCPProvider.project_exists` returns False, in `backend/tests/integration/test_deployment_orchestrator.py` _(shares file with T030/T031 — not parallel)_
- [ ] T048 [US3] Frontend integration test: deployments list renders, empty-state shown when no deployments, auto-refresh on status change, "lost" badge displayed, in `frontend/tests/integration/test_gke_deploy_workflow.py` _(shares file with T034 — not parallel)_

### Implementation for US3

- [ ] T049 [US3] Add `GET /api/deployments` route in `backend/src/api/deployment.py`
- [ ] T050 [US3] Background status-refresh coroutine (poll interval 30 s, uses `GCPProvider.project_exists` + `kube_client`) scheduled on FastAPI lifespan startup, in `backend/src/services/deployment_orchestrator.py`
- [ ] T051 [P] [US3] `api_client.list_deployments` in `frontend/src/services/api_client.py`
- [ ] T052 [US3] Deployments list component with status badges (queued/deploying/running/failed/deleting/lost) and copy-to-clipboard for endpoint URL, in `frontend/src/components/deployments_list.py`
- [ ] T053 [US3] Add "Deployments" tab in `frontend/src/app.py`

**Checkpoint**: US3 complete. Users can see everything they have deployed.

---

## Phase 6: User Story 4 — Delete a Deployment (Priority: P4)

**Goal**: User deletes any of their deployments → platform tears down entire GCP project → deployment removed from list. Lost records can be dismissed. Credentials cannot be deleted while active deployments exist. Invalid credentials block new deployments and deletes, with a persistent warning.

**Independent Test**: Create a `running` deployment via fake; DELETE `/api/deployments/{id}` → 202; watch status → `deleting` → `deleted`; verify `FakeGCPProvider.delete_project` was called for the matching project id.

### Tests for US4 (write first)

- [ ] T054 [US4] Contract tests for `DELETE /api/deployments/{id}` (202 + status=deleting, 404 not owner, 401 no session, 409 when credentials invalid) in `backend/tests/contract/test_deployment_api.py`
- [ ] T055 [US4] Contract tests for `POST /api/deployments/{id}/dismiss` (204 when status=lost, 409 otherwise, 404 not owner) — same file `backend/tests/contract/test_deployment_api.py`
- [ ] T056 [US4] Integration test: deleting an in-progress deployment cancels the orchestrator job and transitions through `deleting→deleted` with cleanup calls verified, in `backend/tests/integration/test_deployment_orchestrator.py` _(shares file with T030/T031/T047 — not parallel)_
- [ ] T057 [P] [US4] Integration test: GCPProvider `validate_credentials` failure during any background refresh flips `validation_status` to `invalid` and causes subsequent `POST /api/deployments` + `DELETE` to return 409; running deployments remain unaffected, in `backend/tests/integration/test_credentials_invalidation.py`
- [ ] T058 [US4] Frontend integration test: delete confirmation dialog, post-dismiss the "lost" record disappears, persistent credential-invalid warning banner, in `frontend/tests/integration/test_gke_deploy_workflow.py` _(shares file with T034/T048 — not parallel)_

### Implementation for US4

- [ ] T059 [US4] Extend `GCPProvider.delete_project` on both Real + Fake in `backend/src/services/gcp_provider.py` and `backend/src/services/gcp_fake_provider.py`
- [ ] T060 [US4] `DELETE /api/deployments/{id}` route (checks cred validity, transitions to `deleting`, schedules teardown) in `backend/src/api/deployment.py`
- [ ] T061 [US4] `POST /api/deployments/{id}/dismiss` route (only valid for `lost`, hard-removes DB row) — same file `backend/src/api/deployment.py`
- [ ] T062 [US4] Orchestrator teardown flow (cancellable async task; idempotent; marks `deleted` on success, `failed` on error with retry-eligible flag) in `backend/src/services/deployment_orchestrator.py`
- [ ] T062a [US4] Background credential re-validation (satisfies FR-015 / makes T057 pass): in `backend/src/services/gcp_provider.py` (or a thin wrapper in `deployment_orchestrator.py` + teardown workflow + status-refresh job), catch `google.api_core.exceptions.PermissionDenied` and `Unauthenticated` raised during any GCPProvider call made on behalf of a user. When caught, flip the owning row in `gcp_credentials` to `validation_status='invalid'`, persist `validation_error_message`, update `last_validated_at`, and emit a structured log event. Running deployments must NOT be torn down — only new `create_deployment` / `delete_deployment` calls are blocked (enforced in T042 and T060). Add a shared helper `record_credentials_invalid(user_id, error)` in `backend/src/services/credentials_store.py` so orchestrator, teardown, and status-refresh all update the DB consistently.
- [ ] T063 [US4] Guard in credentials_store.delete: reject when any deployment with status in `(queued, deploying, running, deleting)` exists for the user. In `backend/src/services/credentials_store.py`
- [ ] T064 [P] [US4] `api_client.delete_deployment`, `api_client.dismiss_deployment` in `frontend/src/services/api_client.py`
- [ ] T065 [US4] Delete-with-confirmation button + dismiss-lost button wired into the list in `frontend/src/components/deployments_list.py`
- [ ] T066 [US4] Persistent "GCP credentials invalid — update to unblock deploy/delete" warning banner in `frontend/src/app.py`

**Checkpoint**: US4 complete. Full deployment lifecycle end-to-end.

---

## Phase 7: User Story 5 — Run Inference on a Deployed Model (Priority: P5)

**Goal**: User submits a prompt through the in-platform panel; backend proxies it to the deployment's public endpoint with a 120 s timeout; response displayed inline.

**Independent Test**: With a `running` deployment (fake endpoint that returns a canned OpenAI-style response), POST `/api/deployments/{id}/inference` with a messages payload → receive 200 with model content; simulate slow endpoint → receive 504 after 120 s.

### Tests for US5 (write first)

- [ ] T067 [US5] Contract tests for `POST /api/deployments/{id}/inference` (200 happy path with canned upstream, 409 when deployment not running, 504 on upstream timeout, 404 not owner) in `backend/tests/contract/test_deployment_api.py`
- [ ] T068 [US5] Frontend integration test: prompt input, loading indicator visible for up-to-120 s, final response rendered, timeout error on artificially delayed upstream, in `frontend/tests/integration/test_gke_deploy_workflow.py` _(shares file with T034/T048/T058 — not parallel)_

### Implementation for US5

- [ ] T069 [US5] `inference_proxy.forward(endpoint_url, body)` with `httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=10, pool=5))`, mapping upstream errors to FastAPI HTTPException codes, in `backend/src/services/inference_proxy.py`
- [ ] T070 [US5] `POST /api/deployments/{id}/inference` route (only for status=running; uses `inference_proxy`) in `backend/src/api/deployment.py`
- [ ] T071 [P] [US5] `api_client.run_inference` in `frontend/src/services/api_client.py`
- [ ] T072 [US5] Inference panel component (prompt text area, send button, loading state, response render, retry on error/timeout) in `frontend/src/components/inference_panel.py`
- [ ] T073 [US5] Integrate inference panel into deployment row detail view in `frontend/src/components/deployments_list.py`

**Checkpoint**: US5 complete. All five stories independently deliverable.

---

## Phase 8: Polish & Cross-Cutting

**Purpose**: Documentation, lint pass, quickstart walkthrough, cleanup.

- [ ] T074 [P] Update `backend/README.md` with: new env vars (`LLMOPS_ENCRYPTION_KEY`), data dir, new routes list
- [ ] T075 [P] Update `frontend/README.md` (or `frontend/src/app.py` docstring) describing new tabs
- [ ] T076 [P] Run `cd backend && ruff check . --fix` and resolve any new lints in feature files
- [ ] T077 [P] Run `cd frontend && ruff check . --fix` and resolve any new lints in feature files
- [ ] T078 _(moved to T042a in Phase 4 — US2)_ Public-repo mock removal happens alongside the new real deploy route so the two code paths never coexist; leave this line as a back-reference only.
- [ ] T079 Manual walkthrough of `specs/007-gke-inference-pipeline/quickstart.md` end-to-end using `FakeGCPProvider` to validate every step renders correctly in the UI
- [ ] T080 [P] Run full test suite (`cd backend && pytest` + `cd frontend && pytest`) — all tests must pass with zero cloud calls (verified by T014 guard)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no deps — can begin immediately
- **Phase 2 (Foundational)**: depends on Setup — **blocks all user stories**
- **Phase 3 (US1)**: depends on Phase 2
- **Phase 4 (US2)**: depends on Phase 2; does NOT depend on US1 for implementation (but manual test requires credentials saved, so practical ordering is US1 → US2)
- **Phase 5 (US3)**: depends on Phase 2 + at least part of US2 (needs the DB rows to list)
- **Phase 6 (US4)**: depends on Phase 2 + US2 (delete operates on real deployment rows)
- **Phase 7 (US5)**: depends on Phase 2 + US2 (needs running deployment to proxy to)
- **Phase 8 (Polish)**: depends on all selected stories

### User Story Dependencies

- **US1**: independent after Phase 2
- **US2**: technically independent after Phase 2; uses credentials from US1 at runtime but contract tests inject credentials directly
- **US3, US4, US5**: each depends on US2 being at least partially in place (they operate on deployment rows)

### Within Each User Story (TDD cycle)

1. Write test tasks first (T-numbers listed under "Tests for USn")
2. Confirm tests fail
3. Implement minimum code to make tests pass
4. Refactor
5. Move to next story

---

## Parallel Execution Examples

### Example A: Phase 2 Foundational (after T005 completes)

```
T006 [P] backend/src/db/models.py
T007 [P] backend/src/db/migrations.py
T009 [P] backend/src/services/crypto.py
T010 [P] backend/src/services/gcp_provider.py
T011 [P] backend/src/services/gcp_fake_provider.py
T013 [P] backend/tests/contract/conftest.py
T014 [P] backend/tests/contract/test_test_isolation.py
```

All seven touch different files and have no cross-dependencies.

### Example B: US2 Implementation (after T028–T034 tests are red)

```
T035 [P] backend/src/models/deployment.py
T036 [P] backend/src/services/deployment_store.py
T037 [P] backend/src/services/hf_models.py
T038 [P] backend/src/services/vllm_manifest.py
T039 [P] backend/src/services/kube_client.py
T043 [P] frontend/src/services/api_client.py
```

All six are in distinct files and can proceed concurrently. T040 (edits `gcp_provider.py` / `gcp_fake_provider.py`) and T041 (edits `deployment_orchestrator.py`) must run after T035–T039 are in, since they integrate their outputs.

### Example C: Test-writing parallelism within US4

Within US4's test-writing phase only **T057** (`backend/tests/integration/test_credentials_invalidation.py`) lives in its own file and can be written in parallel with unrelated work. **T054, T055, T056, and T058 all share files with earlier-story tests** (`test_deployment_api.py`, `test_deployment_orchestrator.py`, `test_gke_deploy_workflow.py`) and therefore drop `[P]` — they must be appended sequentially to avoid merge conflicts. The bigger parallelism win across US3 + US4 is instead between *stories* (e.g., T051 frontend api-client edits ‖ T057 credential-invalidation test ‖ T064 frontend api-client edits) when they touch distinct files.

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational)
2. Complete Phase 3 (US1) under strict TDD
3. Validate: a user can save, validate, and delete GCP credentials; they persist across restarts; API never leaks secrets
4. Ship as the v1 MVP of feature 007

### Incremental Delivery

1. MVP = US1 (credentials onboarding)
2. + US2 = real public-model deployment (core value)
3. + US3 = visibility into deployments
4. + US4 = full lifecycle control
5. + US5 = in-platform inference convenience

### Parallel Team Strategy

- Phase 1 + 2 must complete sequentially by a single developer to keep the foundational wiring consistent.
- After Phase 2:
  - Dev A: US1 (end-to-end)
  - Dev B: US2 implementation scaffolding (T035–T039 can start in parallel with US1)
  - Dev C: starts writing US2 tests (T028–T034) against the `FakeGCPProvider` contract

---

## Testing Policy Compliance

All test tasks in this plan use `FakeGCPProvider` and a per-test temp SQLite file. **No test calls real GCP.** The opt-in `tests/dryrun/` suite (T033) uses Kubernetes server-side `dry_run=["All"]` against a user-supplied scratch kubeconfig — still zero cloud side effects, still zero GCP calls. T014 actively enforces this with an import guard test.

---

## Notes

- Task count: **82 tasks** across 8 phases (T042a + T062a added during remediation; T078 retained as a back-reference pointing to T042a so numbering downstream is unchanged).
- Stories per task: US1 = 13 tasks, US2 = **18** (was 17; +T042a public-repo mock removal moved up from Polish), US3 = 9, US4 = **14** (was 13; +T062a background credential-invalidation detection), US5 = 7. Setup+Foundational = 14. Polish = 7 (T078 now a pointer, no work remains there).
- [P] tasks flagged: **33** across all phases (verified by direct file count). Remediation removed 6 incorrect same-file `[P]` markers from T031/T047/T056 (share `test_deployment_orchestrator.py`) and T048/T058/T068 (share `test_gke_deploy_workflow.py`). The 5 `[P]` markers on `frontend/src/services/api_client.py` (T025, T043, T051, T064, T071) are retained because they sit in different phases — see the clarified `[P]` definition at the top of this file.
- Remediation applied from `/speckit.analyze` findings: **C1** (HIGH — FR-015 credential-invalidation impl gap), **F1/F2** (MEDIUM — `[P]` on co-located test files), **O1** (MEDIUM — mock removal reordered from Polish into US2). LOW-severity items (U1 deleted-status lifecycle detail, U2 UI retry for failed delete, R1 personal-mock regression test) intentionally deferred — they do not block implementation.
- Independent test for each story is spelled out at the start of its phase.
- Every implementation task has a concrete file path.
- Commit after each task (or small logical group). Stop at any checkpoint to validate before continuing.
