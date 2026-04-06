# Research & Technical Decisions: Folder Upload and Public Repository Deployment

## Multi-Folder Upload: Conveying Folder Structure over Multipart

**Decision**: Encode the folder name as a path prefix in each uploaded file's `filename` field (e.g., `my_weights/model.bin`, `tokenizer/vocab.json`). The backend reconstructs subdirectories from these paths when building the temp directory before calling `upload_folder`.

**Rationale**: The existing `POST /api/upload/start` already accepts `list[UploadFile]`. Each `UploadFile` has a `filename` attribute. By convention-over-protocol, prefixing the filename with `<folder_name>/` lets the backend reconstruct the exact folder structure with zero new form fields or schema changes. The `huggingface_hub.upload_folder` call remains untouched — it naturally preserves directory structure from the temp directory tree.

**Alternatives considered**:
- Separate JSON `folder_structure` form field mapping folder names to file indices — rejected because it adds a synchronisation burden (client must maintain index alignment) and complicates the multipart payload.
- New `POST /api/upload/multi-folder` endpoint — rejected per Constitution Principle VI (simplicity, minimal code impact); the existing endpoint can handle the case with a one-line change to path handling.
- Zip-based upload (users zip their folders) — rejected because it requires a zip/unzip step on both sides and degrades UX.

**Security note**: The backend MUST sanitise the path prefix — strip leading `/`, reject `..` traversal segments — before writing to the temp directory. Any file whose sanitised relative path is empty falls back to the root of the temp directory.

---

## Streamlit Folder Selection UI

**Decision**: Simulate folder-grouped uploads via a dynamic session-state-driven UI: each "folder" is a `(text_input for name, file_uploader for files)` pair. Users add folder groups dynamically; a session-state counter tracks how many groups exist.

**Rationale**: Streamlit's `st.file_uploader` does not expose the browser's `<input webkitdirectory>` attribute, so native folder picking is unavailable. The dynamic group approach maps directly to the spec's "select multiple folders" requirement while staying within the Streamlit component model. Each group's files are sent with the folder name as a path prefix (see above decision).

**Alternatives considered**:
- Custom Streamlit component wrapping `<input type="file" webkitdirectory>` — rejected because it requires JavaScript packaging and introduces a non-Python build step, violating Constitution Principle III (direct framework usage).
- Single flat file uploader with a path-prefix text field — rejected because it conflates all folders into one input, making per-folder validation (empty folder detection, conflict detection) impossible.

---

## Public Model Metadata: HuggingFace Hub API

**Decision**: Use `HfApi().model_info(repo_id, token=None)` (unauthenticated) to fetch public repository metadata. Surface `modelId`, `author`, `cardData.description`, `siblings` (file list), and computed `total_size_bytes` from sibling `rfilename` + `size` attributes.

**Rationale**: `huggingface_hub` is already a project dependency. `model_info()` works without a token for public repos and raises `RepositoryNotFoundError` for missing/private repos, giving a clean error mapping to HTTP 404/403 with no extra parsing. Computing total size from `siblings` is straightforward and avoids an additional API call.

**Alternatives considered**:
- Direct `requests` call to HF REST API (`/api/models/{repo_id}`) — rejected per Constitution Principle III (use the library directly).
- Storing/caching model info server-side — rejected per Constitution Principle VI (no persistence needed; this is a one-time pre-deploy metadata fetch).

---

## Public Repo Deploy: Flow Integration

**Decision**: The new "Deploy a Public Repository" section lives inside the existing Deploy tab. Users type a repo ID, click "Fetch Info" to validate and preview metadata, then use the existing CPU/GPU deploy buttons (which set `selected_model` in session state and call `POST /api/deployment/mock`). No new backend deploy endpoint is needed.

**Rationale**: The mock deployment endpoint already accepts any `model_repository` string. The public repo flow simply provides an alternative way to set `selected_model` — via a metadata-validated public repo ID rather than via upload. Reusing the existing deploy buttons avoids duplicating deployment logic.

**Alternatives considered**:
- Separate `POST /api/deployment/public-mock` endpoint — rejected because `POST /api/deployment/mock` is already generic (it takes any `model_repository` string, whether the model lives in the user's account or is public).

---

## Folder Conflict Detection: Frontend-Only Validation

**Decision**: Conflict detection (two queued folders sharing the same name) is performed entirely on the frontend at the time the second conflicting folder group's name is entered. The upload button is disabled and a validation error is shown until all folder names are unique. No backend validation is added.

**Rationale**: Since folder names are user-typed text inputs (not system-generated paths), conflicts can only arise from user error. Detecting this client-side (before any network call) gives instant feedback and prevents wasted upload requests. The backend temp-directory construction would silently merge files from duplicate names — making frontend-only validation the correct layer.

**Alternatives considered**:
- Backend 422 response for duplicate prefixes — rejected because it only catches the error after files are already uploaded to the server, giving a poor UX.
