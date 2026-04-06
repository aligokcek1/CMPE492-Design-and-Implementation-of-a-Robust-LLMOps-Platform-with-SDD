# Tasks: Folder Upload and Public Repository Deployment

**Input**: Design documents from `specs/005-folder-upload-repo-deploy/`  
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/api.yml ✅  
**TDD**: Required by Constitution — test tasks are written and verified to FAIL before every implementation task.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on each other)
- **[Story]**: User story this task belongs to (US1, US2, US3)
- Paths use `backend/` + `frontend/` layout per plan.md

---

## Phase 1: Setup (Baseline Verification)

**Purpose**: Confirm the existing test suite is green before any changes land. This is the TDD baseline.

- [x] T001 Run `cd backend && pytest` and confirm all existing contract tests pass
- [x] T002 [P] Run `cd frontend && pytest` and confirm all existing integration tests pass

**Checkpoint**: Green baseline — no regressions before feature work begins.

---

## Phase 2: Foundational (Shared Backend Model)

**Purpose**: Add the `PublicModelInfoResponse` Pydantic model needed by US2's endpoint. Done first so US1 and US2 can start in parallel after this.

- [x] T003 Add `PublicModelInfoResponse` Pydantic model (`repo_id`, `author`, `description`, `file_count`, `size_bytes`) to `backend/src/models/upload.py`

**Checkpoint**: Foundation ready — US1 and US2 can now be worked on independently.

---

## Phase 3: User Story 1 — Multi-Folder Upload (Priority: P1) 🎯 MVP

**Goal**: Users select multiple named folder groups in the UI; all folders upload into one HF repository, each as a subdirectory. Per-folder success/failure is reported after the batch completes.

**Independent Test**: Select two folder groups (`weights/`, `tokenizer/`), upload to `testuser/my-model`, verify both subdirectories appear in the HF repo.

### Tests for User Story 1

> **Write these tests FIRST and verify they FAIL (red) before any implementation.**

- [x] T004 [P] [US1] Add `test_upload_multi_folder_success` — two folder groups, files with `folder/file` path prefix → 200, `session_id` returned, mock `upload_model_folder` called twice in `backend/tests/contract/test_upload_api.py`
- [x] T005 [P] [US1] Add `test_upload_path_traversal_rejected` — filename `../../etc/passwd` → 400 in `backend/tests/contract/test_upload_api.py`
- [x] T006 [P] [US1] Add `test_upload_mixed_root_and_folder_files` — some files with prefix, some without → 200 in `backend/tests/contract/test_upload_api.py`
- [x] T007 [P] [US1] Add `test_upload_empty_folder_name_rejected` — file with path prefix `"/file.bin"` (empty folder name) falls back to root, not rejected → 200 in `backend/tests/contract/test_upload_api.py`
- [x] T008 [P] [US1] Add `test_multi_folder_ui_renders_add_folder_button` — authenticated session, Upload tab has "+ Add Folder" button in `frontend/tests/integration/test_workflow.py`
- [x] T009 [P] [US1] Add `test_multi_folder_upload_blocks_on_duplicate_name` — two folder groups with same name → upload button absent or disabled in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 1

- [x] T010 [US1] Update `backend/src/api/upload.py`: replace `os.path.basename` with path-prefix-aware logic — sanitise each `upload_file.filename` (strip leading `/`, reject `..` segments → raise 400), create subdirectory tree under `tmp_dir`, write file to its sanitised relative path
- [x] T010b [P] [US1] Add `test_upload_size_limit_exceeded` contract test — total file size exceeds platform limit → 413 response in `backend/tests/contract/test_upload_api.py`; write test FIRST, verify it FAILS before T010c
- [x] T010c [US1] Enforce max upload size limit in `frontend/src/components/upload.py`: before calling `start_upload`, compute total bytes across all folder groups; if total exceeds the platform limit (defined as a constant `MAX_UPLOAD_BYTES`), show `st.error` and abort — do not send the request (depends on T013)
- [x] T011 [US1] Update `upload_model_folder` in `backend/src/services/huggingface.py`: replace the single `api.upload_folder(folder_path=local_path, repo_id=repo_id)` call with a per-folder loop — iterate over each subdirectory found under `local_path`, call `api.upload_folder(folder_path=subdir, repo_id=repo_id, repo_type="model", path_in_repo=folder_name)` for each, wrap each call in try/except to collect per-folder `FolderUploadResult`; all folders are attempted regardless of individual failures (satisfies FR-006)
- [x] T012 [US1] Update `backend/src/models/upload.py`: add `FolderUploadResult` (`folder_name`, `status`, `error`) and update `UploadStartResponse` to include `folder_results: list[FolderUploadResult]`
- [x] T013 [US1] Rewrite `render_upload_section` in `frontend/src/components/upload.py`: session-state list `folder_groups` (each entry: `{name: str, files: list}`); render one `(st.text_input, st.file_uploader)` pair per group; "**+ Add Folder**" button appends an empty group; "Remove" button removes a group; validate on render — blank names, duplicate names, empty file lists each show `st.error` on the affected group and disable the upload button
- [x] T014 [US1] Update `frontend/src/services/api_client.py`: update `start_upload` to build multipart files list with `folder_name/filename` prefixes from the folder groups
- [x] T015 [US1] Update `render_upload_section` in `frontend/src/components/upload.py`: after a successful batch upload, display per-folder result summary (✅ success / ❌ error with message for each folder in `folder_results`)

**Checkpoint**: Multi-folder upload end-to-end functional. Run `cd backend && pytest tests/contract/test_upload_api.py` and `cd frontend && pytest` — all green.

---

## Phase 4: User Story 2 — Public Repository Deployment (Priority: P2)

**Goal**: User types a public HF repo ID (e.g., `bert-base-uncased`), fetches and previews its metadata, then triggers a mocked cloud deployment via CPU or GPU.

**Independent Test**: Type `bert-base-uncased` in the public repo input, click "Fetch Repository Info", verify author/file count shown, click CPU deploy, verify `mock_success` displayed after ~2s.

### Tests for User Story 2

> **Write these tests FIRST and verify they FAIL (red) before any implementation.**

- [x] T016 [P] [US2] Add `test_get_public_model_success` — valid public repo → 200, shape matches `PublicModelInfoResponse` in `backend/tests/contract/test_models_api.py`
- [x] T017 [P] [US2] Add `test_get_public_model_not_found` — `RepositoryNotFoundError` raised by service → 404 in `backend/tests/contract/test_models_api.py`
- [x] T018 [P] [US2] Add `test_get_public_model_private` — `HfHubHTTPError` 403 from service → 403 in `backend/tests/contract/test_models_api.py`
- [x] T019 [P] [US2] Add `test_get_public_model_invalid_format` — `repo_id=justname` (no slash) → 400 in `backend/tests/contract/test_models_api.py`
- [x] T020 [P] [US2] Add `test_get_public_model_missing_token` — no Authorization header → 401 in `backend/tests/contract/test_models_api.py`
- [x] T021 [P] [US2] Add `test_public_repo_deploy_section_renders` — authenticated, Deploy tab contains a text input for public repo ID in `frontend/tests/integration/test_workflow.py`
- [x] T022 [P] [US2] Add `test_public_repo_fetch_info_displays_metadata` — mock `fetch_public_model_info` returns metadata, verify author + file count shown in `frontend/tests/integration/test_workflow.py`
- [x] T023 [P] [US2] Add `test_public_repo_deploy_triggers_mock_deploy` — after fetch, CPU button click → `mock_deploy` called with public `repo_id` in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 2

- [x] T024 [US2] Add `fetch_public_model_info(repo_id: str) -> dict` to `backend/src/services/huggingface.py`: call `HfApi().model_info(repo_id, token=None)` in an executor; compute `file_count` from `siblings`; compute `size_bytes` by summing `s.size` (set to `None` if any sibling lacks size); let `RepositoryNotFoundError` and `HfHubHTTPError` propagate to the API layer
- [x] T025 [US2] Add `GET /api/models/public` route to `backend/src/api/models.py`: validate caller is authenticated; validate `repo_id` matches `^[\w\-\.]+\/[\w\-\.]+$` → 400 on mismatch; call `fetch_public_model_info`; map `RepositoryNotFoundError` → 404, `HfHubHTTPError` 403 → 403, other exceptions → 500; return `PublicModelInfoResponse`
- [x] T026 [P] [US2] Add `fetch_public_model_info(token: str, repo_id: str) -> dict` to `frontend/src/services/api_client.py`: `GET /api/models/public?repo_id={repo_id}` with Bearer token, 15s timeout
- [x] T027 [US2] Add `render_public_repo_deploy_section()` to `frontend/src/components/deploy.py`: `st.text_input` for repo ID; "**Fetch Repository Info**" button calls `fetch_public_model_info`; on success store in `st.session_state["public_repo_info"]` and display metadata in `st.info` block (repo ID, author, description if any, file count, human-readable size); 404 → `st.error("Repository not found …")`; 403 → `st.error("Repository is private …")`; 400 → `st.error("Invalid format …")`; CPU/GPU deploy buttons (enabled only after successful fetch) call `mock_deploy(token, repo_id, resource_type)` and display result
- [x] T028 [US2] Wire `render_public_repo_deploy_section` into the Deploy tab in `frontend/src/app.py`: add `st.divider()` then call the new function below the existing `render_deployment_section()` call

**Checkpoint**: Public repo deploy end-to-end functional. Run `cd backend && pytest tests/contract/test_models_api.py` and `cd frontend && pytest` — all green.

---

## Phase 5: User Story 3 — Upload and Deployment Progress Tracking (Priority: P3)

**Goal**: Real-time feedback during multi-folder upload (per-folder status as each completes) and a clear spinner during mock deployment.

**Independent Test**: Upload three folder groups; verify a progress bar or status indicator updates after each folder completes. Trigger mock deployment; verify spinner visible during the ~2s delay.

### Tests for User Story 3

> **Write these tests FIRST and verify they FAIL (red) before any implementation.**

- [x] T029 [P] [US3] Add `test_upload_shows_per_folder_progress` — after upload completes, UI shows per-folder result rows (success/error) in `frontend/tests/integration/test_workflow.py`
- [x] T030 [P] [US3] Add `test_public_deploy_spinner_visible` — mock `mock_deploy` to block, verify `st.spinner` text is shown during deployment in `frontend/tests/integration/test_workflow.py`

### Implementation for User Story 3

- [x] T031 [US3] Add progress feedback to `render_upload_section` in `frontend/src/components/upload.py`: show an `st.spinner("Uploading folders…")` while `start_upload` is in-flight; once the batch response arrives, render `st.progress(successes / total)` and a per-folder result row (✅/❌) for each entry in `folder_results` — this leverages the `folder_results` list already returned by T012
- [x] T032 [US3] Verify `st.spinner` is correctly scoped in `render_public_repo_deploy_section` in `frontend/src/components/deploy.py` (covers the `mock_deploy` call); update spinner text to show resource type and repo ID for clarity: `f"Deploying {repo_id} on {resource_type}…"`

**Checkpoint**: All three user stories independently functional and all tests green.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T033 [P] Run `ruff check .` in both `backend/` and `frontend/` and fix any linting errors introduced by this feature
- [x] T034 [P] Update `specs/005-folder-upload-repo-deploy/quickstart.md` if any API details changed during implementation
- [x] T035 Run full test suite: `cd backend && pytest` + `cd frontend && pytest` — confirm zero failures
- [x] T036 [P] Manual smoke test per `quickstart.md`: upload two folders to a real HF test repo, fetch info for a public repo (`bert-base-uncased`), trigger CPU mock deploy — verify end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Baseline)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — `PublicModelInfoResponse` model needed before US2 endpoint
- **Phase 3 (US1)**: Depends on Phase 2 completion
- **Phase 4 (US2)**: Depends on Phase 2 completion — independent of Phase 3
- **Phase 5 (US3)**: Depends on Phase 3 AND Phase 4 completion (enhances both)
- **Phase 6 (Polish)**: Depends on Phase 5

### User Story Dependencies

- **US1 (P1)**: Can start after T003 — no dependency on US2
- **US2 (P2)**: Can start after T003 — no dependency on US1
- **US3 (P3)**: Depends on US1 (T015 provides per-folder results) and US2 (T027 provides spinner scope)

### Within Each User Story

```
[Tests written & failing] → [Models] → [Services] → [API / Frontend components] → [Wiring] → [Tests passing]
```

- T004–T009 (US1 tests) → T010–T012 (US1 backend) → T013–T015 (US1 frontend)
- T016–T023 (US2 tests) → T024–T025 (US2 backend) → T026–T028 (US2 frontend)
- T029–T030 (US3 tests) → T031–T032 (US3 frontend)

### Parallel Opportunities

Within Phase 3 (US1): T004–T009 can all run in parallel (different test functions, same file or different files)  
Within Phase 4 (US2): T016–T023 can all run in parallel  
Phase 3 and Phase 4 can be worked on by separate developers simultaneously after T003

---

## Parallel Example: User Story 1 Tests

```bash
# All US1 contract tests can be written together (same file, different functions):
T004: test_upload_multi_folder_success
T005: test_upload_path_traversal_rejected
T006: test_upload_mixed_root_and_folder_files
T007: test_upload_empty_folder_name_rejected

# US1 frontend tests (different file, parallel):
T008: test_multi_folder_ui_renders_add_folder_button
T009: test_multi_folder_upload_blocks_on_duplicate_name
```

## Parallel Example: User Story 2 Tests

```bash
# All US2 backend contract tests (same file, parallel authoring):
T016–T020: backend/tests/contract/test_models_api.py

# US2 frontend tests (different file, parallel):
T021–T023: frontend/tests/integration/test_workflow.py

# US2 frontend client + backend service (different files, parallel):
T026: frontend/src/services/api_client.py  ← parallel with T024
T024: backend/src/services/huggingface.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify baseline (T001–T002)
2. Complete Phase 2: Add shared model (T003)
3. Complete Phase 3: Multi-folder upload (T004–T015)
4. **STOP and VALIDATE**: run both test suites, manually upload two folders
5. Demo: folder groups visible in UI, both appear as subdirs in HF repo

### Incremental Delivery

1. Setup + Foundational → T001–T003
2. **US1 complete** (T004–T015) → Demo multi-folder upload ✅
3. **US2 complete** (T016–T028) → Demo public repo deploy ✅
4. **US3 complete** (T029–T032) → Demo progress indicators ✅
5. Polish (T033–T036) → Production-ready

### Parallel Team Strategy (if 2 developers)

After T003 is merged:
- **Developer A**: Phase 3 (US1) — `backend/src/api/upload.py`, `frontend/src/components/upload.py`
- **Developer B**: Phase 4 (US2) — `backend/src/services/huggingface.py`, `backend/src/api/models.py`, `frontend/src/components/deploy.py`

Both developers write their tests first, merge independently, then Phase 5 polish is done together.

---

## Notes

- `[P]` tasks touch different files with no cross-dependency — safe to parallelize
- TDD is mandatory (Constitution IV): run `pytest` after writing each test to confirm it **fails** before writing production code
- Never mark a task complete without a passing test (Constitution V)
- Commit after each logical group (end of each story phase at minimum)
- The `upload_model_folder` service in `huggingface.py` gains a new `path_in_repo` parameter (T011) — existing callers pass `path_in_repo=None` (default), which preserves backward compatibility
