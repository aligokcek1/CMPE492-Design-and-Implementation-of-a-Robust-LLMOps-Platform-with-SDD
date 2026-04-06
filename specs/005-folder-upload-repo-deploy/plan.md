# Implementation Plan: Folder Upload and Public Repository Deployment

**Branch**: `005-folder-upload-repo-deploy` | **Date**: 2026-04-07 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/005-folder-upload-repo-deploy/spec.md`

## Summary

Extend the existing single-file upload pipeline to accept **multiple folder groups** in one request. Each folder group is conveyed via filename path prefixes (`folder_name/file`); the backend reconstructs the directory tree in a temp directory and then calls `api.upload_folder()` **once per folder subdirectory** (using `path_in_repo=folder_name`), enabling per-folder error isolation (FR-006) and result reporting. Add a new `GET /api/models/public` endpoint and a corresponding frontend section that lets users type a public HF repository ID, preview its metadata, and trigger the existing mock GCP deployment — all without downloading any files locally.

## Technical Context

**Language/Version**: Python 3.11 (Backend + Frontend)  
**Primary Dependencies**: FastAPI, huggingface_hub ≥ 0.23.0, Streamlit, pydantic ≥ 2.7.0, pytest, pytest-asyncio, httpx  
**Storage**: No new persistent storage — temp filesystem during upload only; HF Hub as the destination  
**Testing**: pytest + pytest-asyncio + httpx AsyncClient (backend contract tests); pytest + streamlit.testing.v1 (frontend integration)  
**Target Platform**: Linux server / local macOS dev  
**Project Type**: Web application (FastAPI backend + Streamlit frontend)  
**Performance Goals**: Public model metadata fetch completes in under 3 seconds for typical public repos; multi-folder upload throughput bounded by HF Hub API limits (unchanged from feature 004)  
**Constraints**: No new dependencies beyond what is already installed; no new database or storage service; token never logged or persisted beyond the browser session  
**Scale/Scope**: Single-user sessions; no concurrent upload queue management required

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Clean & Readable Code | ✅ Pass | All new functions follow existing naming conventions; no unnecessary comments |
| II. Security First | ✅ Pass | Path traversal sanitisation required in `upload.py` before writing to temp dir; token is never logged; public model info endpoint does not echo the token back |
| III. Direct Framework Usage | ✅ Pass | `HfApi().model_info()` called directly; no wrapper classes; Streamlit components used directly |
| IV. TDD Mandatory | ✅ Pass | Contract tests for new endpoint written before implementation; Red-Green-Refactor enforced per task |
| V. Realistic & Comprehensive Testing | ✅ Pass | HF API patched at service layer (not at HTTP level) in contract tests; frontend integration test covers full upload + deploy workflow |
| VI. Simplicity | ✅ Pass | Folder structure encoded in `filename` prefix — one-line backend change; public repo deploy reuses existing mock deploy endpoint |

**Complexity Tracking**: No violations — no new abstractions, no new infrastructure.

## Project Structure

### Documentation (this feature)

```text
specs/005-folder-upload-repo-deploy/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
├── contracts/
│   └── api.yml          ← Phase 1 output (OpenAPI v1.1.0)
├── checklists/
│   └── requirements.md
└── tasks.md             ← Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── api/
│   │   ├── models.py          ← add GET /api/models/public endpoint
│   │   └── upload.py          ← update path sanitisation + subdirectory creation
│   ├── models/
│   │   └── upload.py          ← add FolderUploadResult + update UploadStartResponse to include folder_results
│   └── services/
│       └── huggingface.py     ← add fetch_public_model_info(repo_id)
└── tests/
    └── contract/
        ├── test_models_api.py  ← add public model info contract tests
        └── test_upload_api.py  ← add multi-folder upload contract tests

frontend/
├── src/
│   ├── components/
│   │   ├── upload.py           ← rewrite render_upload_section for multi-folder UI
│   │   └── deploy.py           ← add render_public_repo_deploy_section
│   └── services/
│       └── api_client.py       ← add fetch_public_model_info(token, repo_id)
└── tests/
    └── integration/
        └── test_workflow.py    ← extend with folder upload + public deploy scenarios
```

**Structure Decision**: Option 2 (web application, existing backend/frontend split). No new directories required — all changes extend existing modules.

---

## Phase 0: Research Findings

See [research.md](./research.md) for full rationale. Key resolved decisions:

| Unknown | Resolution |
|---------|-----------|
| How to convey folder structure over existing multipart endpoint | Encode folder name as `filename` prefix (`folder_name/file`); backend creates subdirs from path, then calls `api.upload_folder()` once per folder subdirectory using `path_in_repo=folder_name` |
| Streamlit folder picker | Dynamic session-state-driven folder groups: `(text_input, file_uploader)` pairs per folder |
| HF public model metadata | `HfApi().model_info(repo_id, token=None)` — no auth for public repos; raises `RepositoryNotFoundError` for missing/private |
| Public repo deploy integration | Reuse existing `POST /api/deployment/mock`; new UI section sets `selected_model` then delegates |
| Folder conflict detection layer | Frontend-only, at input time; upload button disabled on conflict |

---

## Phase 1: Design

### Backend Changes

#### 1. `backend/src/services/huggingface.py` — Add `fetch_public_model_info`

New async function:

```python
async def fetch_public_model_info(repo_id: str) -> dict[str, Any]:
    """Fetch metadata for a public HF model repository (no auth required)."""
```

- Calls `HfApi().model_info(repo_id, token=None)` in an executor.
- Returns dict with `repo_id`, `author`, `description`, `file_count`, `size_bytes`.
- Raises `RepositoryNotFoundError` for missing repos (maps to 404 at API layer).
- Raises `HfHubHTTPError` with 403 for private repos (maps to 403).

#### 2. `backend/src/api/models.py` — Add `GET /api/models/public`

New route on the existing `models` router:

```python
@router.get("/models/public", response_model=PublicModelInfoResponse)
async def get_public_model(
    repo_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> PublicModelInfoResponse:
```

- Validates caller is authenticated (token required to prevent unauthenticated scraping).
- Validates `repo_id` matches `owner/repo-name` pattern before calling service; returns 400 on invalid format.
- Maps `RepositoryNotFoundError` → 404; 403 HTTP error from HF → 403; other errors → 500.

New Pydantic response model (add to `backend/src/models/upload.py` or a new `backend/src/models/models.py`):

```python
class PublicModelInfoResponse(BaseModel):
    repo_id: str
    author: str
    description: str | None
    file_count: int
    size_bytes: int | None
```

#### 3. `backend/src/api/upload.py` — Multi-Folder Path Handling + Per-Folder Upload Loop

**Step A — Write files to temp directory with folder structure**:

Replace:
```python
filename = os.path.basename(upload_file.filename or "unnamed_file")
dest = os.path.join(tmp_dir, filename)
```

With logic that:
1. Takes `upload_file.filename` (e.g., `my_weights/model.bin`).
2. Sanitises: strips leading `/`, rejects any `..` segment (raises 400).
3. Reconstructs safe relative path: `safe_rel = posixpath.normpath(filename).lstrip("/")`
4. Creates subdirectory tree: `os.makedirs(os.path.dirname(dest), exist_ok=True)`
5. Writes file to `os.path.join(tmp_dir, safe_rel)`.

**Step B — Per-folder upload loop in `upload_model_folder`** (service layer):

Replace the single `api.upload_folder(folder_path=local_path, repo_id=repo_id)` call with a loop:

```python
for folder_name in sorted(os.listdir(local_path)):
    subdir = os.path.join(local_path, folder_name)
    if os.path.isdir(subdir):
        api.upload_folder(
            folder_path=subdir,
            repo_id=repo_id,
            repo_type="model",
            path_in_repo=folder_name,
        )
```

Each folder upload is isolated in a try/except so that one failure does not abort the rest (satisfying FR-006). Results are collected and returned as `list[FolderUploadResult]` in the updated `UploadStartResponse`.

---

### Frontend Changes

#### 4. `frontend/src/components/upload.py` — Multi-Folder UI

Replace `render_upload_section` with a dynamic folder-groups UI:

- Session state key `folder_groups`: list of dicts `{name: str, files: list}`.
- Initialise with one empty group on first render.
- For each group: `st.text_input` (folder name) + `st.file_uploader` (multiple files).
- `+ Add Folder` button appends a new empty group.
- `Remove` button (per group) removes the group.
- Validate before upload: detect blank names, duplicate names, empty file lists → show `st.error` and disable upload button.
- On upload: build the multipart files list as `(folder_name/filename, bytes, mime)` tuples and call `start_upload`.

#### 5. `frontend/src/components/deploy.py` — Public Repo Deploy Section

Add `render_public_repo_deploy_section()` inside the deploy tab (called from `app.py` after the existing `render_deployment_section`):

- `st.text_input` for public repo ID (placeholder: `owner/repo-name`).
- `Fetch Repository Info` button → calls `fetch_public_model_info(token, repo_id)`.
- On success: display metadata (repo ID, author, description, file count, size) in an `st.info` block.
- Store `repo_id` in `st.session_state["public_repo_id"]` on successful fetch.
- CPU / GPU deploy buttons (same pattern as existing `render_deployment_section`) → call `mock_deploy(token, repo_id, resource_type)`.
- Errors (404, 403, 400) shown via `st.error` with specific messages.

#### 6. `frontend/src/services/api_client.py` — Add `fetch_public_model_info`

```python
def fetch_public_model_info(token: str, repo_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{BACKEND_URL}/api/models/public",
        params={"repo_id": repo_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    _raise_for_status(response)
    return response.json()
```

#### 7. `frontend/src/app.py` — Wire New Section

In the Deploy tab, add a horizontal divider and call `render_public_repo_deploy_section()` below the existing deployment section.

---

### Test Plan (TDD order — write tests first)

#### Backend Contract Tests

**`test_upload_api.py` additions**:
- `test_upload_multi_folder_success` — two folders, files with path prefixes → 200, `session_id` returned.
- `test_upload_path_traversal_rejected` — filename `../etc/passwd` → 400.
- `test_upload_folder_files_mixed_with_root_files` — some files with prefix, some without → 200.

**`test_models_api.py` additions**:
- `test_get_public_model_success` — valid public repo → 200, correct shape.
- `test_get_public_model_not_found` — RepositoryNotFoundError raised → 404.
- `test_get_public_model_private` — HfHubHTTPError 403 raised → 403.
- `test_get_public_model_invalid_format` — `repo_id=justname` → 400.
- `test_get_public_model_missing_token` — no auth header → 401.

#### Frontend Integration Tests

**`test_workflow.py` additions**:
- `test_multi_folder_upload_renders_add_folder_button` — folder groups UI rendered.
- `test_public_repo_deploy_section_renders` — authenticated, deploy tab has public repo input.
- `test_public_repo_fetch_info_displays_metadata` — mock `fetch_public_model_info` → metadata shown.
- `test_public_repo_deploy_triggers_mock_deploy` — after fetch, CPU button → spinner → success.
