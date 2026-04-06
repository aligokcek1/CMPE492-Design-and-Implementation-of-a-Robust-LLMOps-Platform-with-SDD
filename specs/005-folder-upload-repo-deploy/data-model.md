# Data Model: Folder Upload and Public Repository Deployment

## Entities

### `FolderEntry` *(frontend-only, session state)*

Represents a single folder queued for upload within a multi-folder upload session. Managed in `st.session_state` on the frontend; never persisted or sent to the backend as a structured object.

- `name` (string): User-provided folder name. Used as the subdirectory prefix in the target HF repository (e.g., `my_weights`). Must be non-empty, must not contain `/` or `..`, and must be unique within the current session's folder list.
- `files` (list of UploadedFile): Files belonging to this folder, as returned by `st.file_uploader`. May not be empty at upload time.
- `status` (enum): `pending` | `ready` | `error`. Derived from validation state: `error` if name is blank/duplicate or files list is empty; `ready` otherwise.

**Validation rules**:
- `name` MUST match `^[\w][\w\-\.]*$` (alphanumeric, hyphens, underscores, dots; no path separators).
- `name` MUST be unique across all `FolderEntry` instances in the current session.
- `files` MUST contain at least one file before upload is initiated.
- Upload MUST NOT start if any `FolderEntry` has `status = error`.

---

### `LocalModelSession` *(updated)*

Extends the existing model to reflect multi-folder batch uploads.

- `session_id` (uuid): Unchanged.
- `local_path` (string): Temp directory root on the backend, containing one subdirectory per folder. Unchanged semantics.
- `repository_name` (string): Single target HF repository ID for the entire batch (e.g., `username/my-model`). Unchanged.
- `status` (enum): `pending` | `uploading` | `completed` | `failed`. Unchanged.
- `progress` (float): 0.0–1.0 aggregate progress. Unchanged.

**Change from feature 004**: `local_path` now points to a directory tree with folder subdirectories rather than a flat list of files.

---

### `PublicModelInfo` *(new)*

Represents metadata for a publicly accessible Hugging Face model repository, fetched before initiating a public-repo deployment.

- `repo_id` (string): Full repository identifier in `owner/repo-name` format (e.g., `bert-base-uncased`).
- `author` (string): Owner/organisation name extracted from `repo_id`.
- `description` (string | null): Short description from the model card, if available.
- `file_count` (int): Number of files in the repository (from `siblings` list).
- `size_bytes` (int | null): Aggregate size of all repository files in bytes, computed from `siblings[*].size`. May be `null` if size data is unavailable for any file.

**Validation rules**:
- `repo_id` MUST match `^[\w\-\.]+\/[\w\-\.]+$` — enforced by the backend before calling the HF API.
- Repository MUST be publicly accessible; private repositories resolve to a 403 response.
- Non-existent repositories resolve to a 404 response.

---

### `MockDeployment` *(unchanged)*

No changes to the existing deployment model. The `model_repository` field accepts any valid repo ID string, covering both user-owned and public repositories.

- `model_repository` (string): The HF model ID to simulate deploying (user-owned or public).
- `resource_type` (enum): `CPU` | `GPU`.
- `deployment_status` (enum): `pending` | `mock_success`.

---

## State Transitions

### Upload Session Lifecycle

```
[folder groups assembled on frontend]
         │
         ▼ (all FolderEntry.status == ready)
     PENDING
         │ upload initiated
         ▼
    UPLOADING  ──── HF API error ────▶  FAILED
         │
         ▼ (upload_folder returns)
    COMPLETED
```

### FolderEntry Validation State

```
     [user adds folder group]
              │
              ▼
     name blank or invalid ──────▶ ERROR
              │
     name duplicate ─────────────▶ ERROR
              │
     files list empty ────────────▶ ERROR
              │
     all checks pass ─────────────▶ READY
```

### Public Repo Deploy Lifecycle

```
  [user types repo_id]
         │
         ▼ (Fetch Info clicked)
   FETCHING METADATA
         │
   repo not found / private ───▶  ERROR (shown inline)
         │
         ▼
  METADATA PREVIEW SHOWN
         │ (CPU or GPU deploy clicked)
         ▼
    DEPLOYING (spinner)
         │ (~2s mock delay)
         ▼
  MOCK_SUCCESS (result displayed)
```
