# Tasks: GPU / CPU Hardware Selector for Public Model Deployment

**Input**: Design documents from `specs/008-gpu-cpu-deploy/`
**Branch**: `008-gpu-cpu-deploy`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**TDD**: Tests are included (constitution principle IV mandates Red-Green-Refactor). Write each test task before its corresponding implementation task. Verify the test fails (red) before implementing (green).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: User story label (US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install new dependencies so subsequent tasks can import new packages.

- [ ] T001 Add `lightning-sdk` and `litserve` to backend dependencies in `backend/pyproject.toml` (or `backend/requirements.txt` / equivalent file where existing deps are declared)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB schema, Pydantic models, and `DeploymentStore` changes that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Add `LightningAICredentialsRow` SQLAlchemy model and extend `DeploymentRow` with `hardware_type` + `lightning_ai_deployment_id` columns + make `gcp_project_id` / `gke_cluster_name` / `gke_region` nullable in `backend/src/db/models.py`
- [ ] T003 Write structural SQLite migration (table rebuild for `deployments`) + additive `lightning_ai_credentials` table creation in `backend/src/db/migrations.py`; gate rebuild on absence of `hardware_type` column via inspector
- [ ] T004 [P] Add `hardware_type: Literal["cpu", "gpu"]` (required, no default) to `DeployRequest` and `hardware_type: str` to `Deployment` + `DeploymentDetail` response models in `backend/src/models/deployment.py`
- [ ] T005 [P] Create `LightningAICredentialRequest` (field: `api_key: str`) and `LightningAICredentialStatus` (fields: `configured`, `validation_status`, `validation_error_message`, `last_validated_at`) Pydantic models in `backend/src/models/lightning_ai_credentials.py`
- [ ] T006 Update `DeploymentStore.create` to accept `hardware_type: str` parameter and store `None` for GKE-specific columns when `hardware_type == "gpu"`; add `store_lightning_deployment_id(deployment_id, lightning_ai_deployment_id)` method in `backend/src/services/deployment_store.py`

**Checkpoint**: DB schema, Pydantic models, and store layer ready — user story implementation can begin.

---

## Phase 3: User Story 1 — CPU Hardware Selector (Priority: P1) 🎯 MVP

**Goal**: Add a CPU/GPU radio selector to the Deploy UI and wire CPU deployments through the existing GKE path with `hardware_type` tracked end-to-end.

**Independent Test**: Enter a public HF model ID → select CPU → click Deploy → verify the deployment record has `hardware_type="cpu"` and the orchestrator routes to the TGI-CPU manifest path. All existing CPU contract tests must still pass.

### Tests for User Story 1 (write FIRST — verify red before implementing)

- [ ] T007 [P] [US1] Add contract tests to `backend/tests/contract/test_deployment_api.py`: (a) `POST /api/deployments` with `hardware_type="cpu"` returns 202 with `hardware_type="cpu"` in response; (b) `POST /api/deployments` without `hardware_type` returns 422; (c) GET deployment list includes `hardware_type` field on each record
- [ ] T008 [P] [US1] Add frontend AppTest cases to `frontend/tests/integration/test_workflow.py`: (a) Deploy button is disabled when no hardware type selected after model fetch; (b) Deploy button enables after selecting CPU; (c) form submission includes `hardware_type="cpu"` in payload

### Implementation for User Story 1

- [ ] T009 [US1] Render `st.radio(["CPU", "GPU"], index=None, horizontal=True)` hardware selector in `render_public_repo_deploy_section` and disable the Deploy button until both `hardware_type` and model info are set in `frontend/src/components/deploy.py`
- [ ] T010 [US1] Pass `hardware_type` as a parameter to the `deploy_public_model` API call in `frontend/src/services/api_client.py`
- [ ] T011 [US1] Accept `hardware_type` in `POST /api/deployments` request body, pass it to `DeploymentStore.create`, and include it in the 202 response in `backend/src/api/deployment.py`
- [ ] T012 [US1] Update `DeploymentOrchestrator.run_to_terminal` to branch on `row.hardware_type`: CPU → call existing GKE orchestration logic (rename the inner path to `_run_gke` internally); GPU → stub that will be filled in Phase 4 in `backend/src/services/deployment_orchestrator.py`
- [ ] T013 [US1] Map `DeploymentRow.hardware_type` into the `Deployment` and `DeploymentDetail` serialization helpers in `backend/src/api/deployment.py`
- [ ] T014 [US1] Run `cd backend && pytest tests/contract/test_deployment_api.py` and verify all US1 CPU tests pass (green)

**Checkpoint**: Hardware selector visible in UI, CPU deployments tagged `hardware_type="cpu"`, all existing CPU tests passing.

---

## Phase 4: User Story 2 — GPU / Lightning AI Path (Priority: P2)

**Goal**: Full GPU deployment flow — Lightning AI credential management tab, `lightning-sdk` provider, `LitServe+vLLM` script generator, GPU orchestrator path, and GPU delete support.

**Independent Test**: Configure a Lightning AI API key → select GPU → click Deploy → verify the backend calls `lightning_ai_provider.deploy()` with the correct model ID, stores the returned deployment ID, and the deployment record has `hardware_type="gpu"`.

### Tests for User Story 2 (write FIRST — verify red before implementing)

- [ ] T015 [P] [US2] Write contract tests in `backend/tests/contract/test_lightning_ai_credentials_api.py`: GET not-configured (200, `configured=false`), POST valid key (200, `configured=true`, `validation_status="valid"`), POST invalid key (400, code `lightning_auth_error`), DELETE (204), GET after delete (200, `configured=false`)
- [ ] T016 [P] [US2] Add GPU deployment contract tests to `backend/tests/contract/test_deployment_api.py`: GPU happy path (202, `hardware_type="gpu"`), `lightning_credentials_missing` (409), `lightning_credentials_invalid` (409), GPU delete (202 → polling → deleted), inference proxy on GPU endpoint URL; **also** add a mixed-hardware concurrent-limit test: create 2 CPU + 1 GPU deployment (3 active total) → 4th attempt of either type must return 409 `concurrent_deployment_limit` (FR-019)
- [ ] T017 [P] [US2] Add frontend AppTest cases to `frontend/tests/integration/test_workflow.py`: GPU selection enables Deploy button; submitting GPU deploy without Lightning AI key shows a banner directing to ⚡ tab; ⚡ tab renders API key input form

### Implementation for User Story 2 — Provider Layer

- [ ] T018 [P] [US2] Implement `LightningAIProvider` runtime protocol (methods: `deploy`, `get_status`, `delete`, `validate_api_key`) + `RealLightningAIProvider` that calls the `lightning-sdk` client in `backend/src/services/lightning_ai_provider.py`
- [ ] T019 [P] [US2] Implement `FakeLightningAIProvider` with deterministic responses (configurable to succeed or raise `LightningAIAuthError` / `LightningAIServiceError`) in `backend/src/services/lightning_ai_fake_provider.py`

### Implementation for User Story 2 — Credential Store & API

- [ ] T020 [US2] Implement `LightningAICredentialsStore` (methods: `save`, `get_status`, `get_decrypted_key`, `delete`, `record_key_invalid`) using `encrypt`/`decrypt` from `backend/src/services/crypto.py` in `backend/src/services/lightning_ai_credentials_store.py`
- [ ] T021 [US2] Implement `lightning_ai_credentials` API router: `GET ""` → status, `POST ""` → save+validate via provider, `DELETE ""` → delete in `backend/src/api/lightning_ai_credentials.py`
- [ ] T022 [US2] Register `lightning_ai_credentials.router` under `/api/lightning/credentials` prefix in `backend/src/main.py`; add `FakeLightningAIProvider` fixture and provider override to `backend/tests/contract/conftest.py`
- [ ] T022a [US2] Add `get_lightning_ai_provider` dependency function and `reset_lightning_ai_provider_for_tests` override to `backend/src/api/dependencies.py`; export both from `backend/src/main.py` `__all__` (mirrors existing `get_gcp_provider` / `reset_gcp_provider_for_tests` pattern) — required for FastAPI dependency-override injection in contract tests

### Implementation for User Story 2 — GPU Orchestration

- [ ] T023 [P] [US2] Implement `generate(hf_model_id: str) -> str` returning a LitServe + vLLM server script string in `backend/src/services/litserve_gpu.py`
- [ ] T024 [US2] Implement `DeploymentOrchestrator._run_lightning_ai`: decrypt key, generate script via `litserve_gpu.generate`, write to `NamedTemporaryFile`, call `provider.deploy()`, store returned ID via `deployment_store.store_lightning_deployment_id`, update status messages in `backend/src/services/deployment_orchestrator.py`
- [ ] T025 [US2] Update `refresh_statuses` loop body to poll `lightning_ai_provider.get_status()` for GPU rows (branch on `row.hardware_type`); call `record_key_invalid` on `LightningAIAuthError`; update `status` and `status_message` in `backend/src/services/deployment_orchestrator.py`
- [ ] T025a [US2] Update `start_status_refresh_loop` signature to accept both `get_gcp_provider` and `get_lightning_ai_provider` callables; update the lifespan startup call in `backend/src/main.py` to pass both providers — without this GPU rows are never polled in production
- [ ] T026 [US2] Add GPU pre-flight check to `POST /api/deployments` handler: if `hardware_type=="gpu"` and key not configured → 409 `lightning_credentials_missing`; if `validation_status=="invalid"` → 409 `lightning_credentials_invalid` in `backend/src/api/deployment.py`
- [ ] T027 [US2] Add GPU delete support to `DELETE /api/deployments/{id}`: if `hardware_type=="gpu"`, call `lightning_ai_provider.delete()`; treat SDK `NotFound` as success (mirrors GCP not-found handling) in `backend/src/api/deployment.py`
- [ ] T027a [US2] Backend test checkpoint — run `cd backend && pytest tests/contract/test_lightning_ai_credentials_api.py tests/contract/test_deployment_api.py` and verify all US2 backend tests pass (green) before proceeding to frontend tasks

### Implementation for User Story 2 — Frontend

- [ ] T028 [US2] Add `get_lightning_credentials_status`, `save_lightning_credentials`, `delete_lightning_credentials` API client functions to `frontend/src/services/api_client.py`
- [ ] T029 [US2] Implement `render_lightning_ai_credentials_section` component (status panel + API key form + delete button, mirrors `gcp_credentials.py` structure) in `frontend/src/components/lightning_ai_credentials.py`
- [ ] T030 [US2] Add ⚡ Lightning AI tab (6th tab) to the `st.tabs` call and render `render_lightning_ai_credentials_section` inside it in `frontend/src/app.py`
- [ ] T031 [US2] Add GPU error handling to `render_public_repo_deploy_section`: on 409 `lightning_credentials_missing` or `lightning_credentials_invalid`, show `st.error` banner directing the user to the ⚡ Lightning AI tab in `frontend/src/components/deploy.py`

**Checkpoint**: GPU deployments end-to-end — credential management, SDK deploy, status polling, delete, and frontend error messages all working with the fake provider.

---

## Phase 5: User Story 3 — Clear Hardware-Aware User Feedback (Priority: P3)

**Goal**: Every status message, badge, and error shown to the user accurately reflects which hardware type and platform is in use — CPU/GKE or GPU/Lightning AI — with no cross-contamination of labels.

**Independent Test**: Run a CPU deploy and a GPU deploy in sequence; assert that spinner text, deployment list badges, and failure messages are distinctly hardware-specific with no shared generic labels.

### Tests for User Story 3 (write FIRST — verify red before implementing)

- [ ] T032 [P] [US3] Add frontend AppTest assertions to `frontend/tests/integration/test_workflow.py`: CPU deployment row shows "GKE" or "CPU" label AND must NOT contain "Lightning AI"; GPU deployment row shows "Lightning AI" or "GPU" label AND must NOT contain "GKE"; GPU failure message contains "Lightning AI"; GPU deployment in `deploying` state renders a non-empty `status_message` (not a static placeholder) — FR-008 bidirectional non-contamination + FR-015 live status display

### Implementation for User Story 3

- [ ] T033 [US3] Add `hardware_type` badge ("⚙️ CPU / GKE" vs "⚡ GPU / Lightning AI") to each row in `render_deployments_list` in `frontend/src/components/deployments_list.py`
- [ ] T034 [US3] Ensure GPU failure status messages from `_run_lightning_ai` always reference Lightning AI by name and include "check your Lightning AI API key" when the cause is auth-related in `backend/src/services/deployment_orchestrator.py`
- [ ] T035 [US3] Extend `_render_credentials_invalid_banner` to also fetch Lightning AI credential status and show a GPU key-invalid warning alongside (or instead of) the GCP warning when appropriate in `frontend/src/app.py`
- [ ] T036 [US3] Run `cd frontend && pytest` to verify all US3 feedback tests pass (green)

**Checkpoint**: All three user stories independently functional with hardware-specific feedback throughout.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T037 [P] Run `cd backend && ruff check . --fix` and resolve any linting issues introduced by feature 008 files
- [ ] T038 [P] Run `cd frontend && ruff check . --fix` and resolve any linting issues introduced by feature 008 files
- [ ] T039 Run `cd backend && pytest` (full suite) and confirm zero regressions against all pre-existing CPU contract tests
- [ ] T040 Run `cd frontend && pytest` (full suite) and confirm all integration tests pass
- [ ] T041 [P] Add Lightning AI setup instructions (API key, `LLMOPS_ENCRYPTION_KEY` reuse, `pip install lightning-sdk litserve`) to `backend/README.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Requires Phase 1 — **BLOCKS all user stories**
- **Phase 3 (US1)**: Requires Phase 2
- **Phase 4 (US2)**: Requires Phase 2; benefits from Phase 3 selector UI but can start once Phase 2 is done (backend GPU path is independent of frontend US1 changes)
- **Phase 5 (US3)**: Requires Phase 3 and Phase 4 complete
- **Phase 6 (Polish)**: Requires all user story phases

### Within Phase 2

- T002 must complete before T003 (migrations reference models)
- T004, T005 are independent of T002/T003 and of each other [P]
- T006 requires T002 (row fields must exist)

### Within Phase 3 (US1)

- T007, T008 can run in parallel [P] (different files)
- T009, T010 can run in parallel [P] (different files)
- T011, T012, T013 depend on T004 (foundational Pydantic changes) — sequential with each other (same API file: T011 → T013)
- T014 runs after T007–T013

### Within Phase 4 (US2)

- T015, T016, T017, T018, T019, T023 can all run in parallel [P] (different files, no mutual dependency)
- T020 requires T002 (DB models), T005 (Pydantic models), T018 (provider interface)
- T021 requires T020 (store)
- T022 requires T021 (router) and T019 (fake provider fixture)
- T022a requires T022 (depends on provider pattern being established)
- T024 requires T018, T023, T022, T022a (provider, script gen, store, dependency injection all available)
- T025 requires T024 (loop update builds on `_run_lightning_ai` structure)
- T025a requires T025 (signature update follows loop body update)
- T026 requires T020 (credential store to pre-flight check)
- T027 requires T018 (provider delete call)
- T027a runs after T027 (checkpoint after all backend US2 work)
- T028, T029, T030, T031 are independent of each other [P]; T029 requires T028; T030 requires T029; all four can start after T027a checkpoint

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no story dependencies
- **US2 (P2)**: Can start after Phase 2 — UI selector from US1 helpful but not blocking for backend work
- **US3 (P3)**: Must start after US1 AND US2 are complete (feedback covers both paths)

---

## Parallel Execution Examples

### Parallel within Phase 2

```
Parallel group A:
  Task: "T002 – DB models (LightningAICredentialsRow + DeploymentRow)"
  → then: "T003 – migrations" (depends on T002)

Parallel group B (independent of A):
  Task: "T004 – DeployRequest + Deployment Pydantic update"
  Task: "T005 – LightningAICredential Pydantic models"
```

### Parallel within Phase 3 (US1)

```
Parallel group — tests:
  Task: "T007 – CPU contract tests"
  Task: "T008 – frontend AppTest (selector disabled/enabled)"

Parallel group — frontend implementation:
  Task: "T009 – st.radio hardware selector in deploy.py"
  Task: "T010 – hardware_type in api_client.py deploy call"
```

### Parallel within Phase 4 (US2) — early tasks

```
Parallel group — tests + provider stubs:
  Task: "T015 – Lightning AI credential contract tests"
  Task: "T016 – GPU deploy contract tests"
  Task: "T017 – Frontend AppTest GPU + ⚡ tab"
  Task: "T018 – RealLightningAIProvider"
  Task: "T019 – FakeLightningAIProvider"
  Task: "T023 – litserve_gpu.generate()"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete **Phase 1: Setup** (T001)
2. Complete **Phase 2: Foundational** (T002–T006)
3. Complete **Phase 3: User Story 1** (T007–T014)
4. **STOP and VALIDATE**: `cd backend && pytest tests/contract/test_deployment_api.py` passes; hardware selector visible in Streamlit; CPU deployments work end-to-end
5. Demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready (T001–T006)
2. Add US1 (T007–T014) → CPU selector working → Deploy / Demo (**MVP!**)
3. Add US2 (T015–T031) → GPU path live → Deploy / Demo
4. Add US3 (T032–T036) → Full hardware-aware feedback → Deploy / Demo
5. Polish (T037–T041) → Production-ready

---

## Notes

- **[P]** marks tasks with different output files and no dependency on other in-progress tasks — safe to run as parallel agents
- TDD is mandatory (constitution IV): each test task produces a failing test; its implementation task makes it pass
- CPU path (`vllm_manifest.py`, existing orchestrator GKE flow) MUST NOT be renamed or structurally changed (FR-005)
- Lightning AI API key is never returned from any API endpoint — only `validation_status` and metadata
- The structural migration in T003 runs inside a transaction; a failure leaves the old table intact
- Verify `cd backend && pytest` still passes after Phase 3 before starting Phase 4
