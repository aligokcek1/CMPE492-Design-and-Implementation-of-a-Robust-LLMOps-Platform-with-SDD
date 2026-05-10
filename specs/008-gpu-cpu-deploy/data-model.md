# Data Model: GPU / CPU Hardware Selector — Feature 008

**Date**: 2026-05-10 | **Branch**: `008-gpu-cpu-deploy`

---

## 1. New Table: `lightning_ai_credentials`

Stores one row per user's Lightning AI API key. Mirrors `gcp_credentials` in structure.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PK, autoincrement | Internal row ID |
| `user_id` | TEXT | NOT NULL, UNIQUE INDEX | HF username (same as session) |
| `api_key_encrypted` | BLOB | NOT NULL | Fernet-encrypted Lightning AI API key |
| `validation_status` | TEXT | NOT NULL, CHECK IN ('valid','invalid') | Result of last validation call |
| `validation_error_message` | TEXT | nullable | SDK error message if invalid |
| `last_validated_at` | DATETIME | NOT NULL | UTC timestamp of last validation |
| `created_at` | DATETIME | NOT NULL | Row creation time |
| `updated_at` | DATETIME | NOT NULL | Last modification time |

**SQLAlchemy model**: `LightningAICredentialsRow` in `backend/src/db/models.py`

**Security**: `api_key_encrypted` is never returned from any API endpoint. The GET status endpoint returns only `configured`, `validation_status`, `validation_error_message`, and `last_validated_at`.

---

## 2. Modified Table: `deployments`

### New Columns (added via structural migration — see research.md §3)

| Column | Type | Constraints | Description |
|---|---|---|---|
| `hardware_type` | TEXT | NOT NULL, DEFAULT `'cpu'`, CHECK IN ('cpu','gpu') | Deployment target hardware |
| `lightning_ai_deployment_id` | TEXT | nullable | Lightning AI deployment ID for GPU rows; NULL for CPU rows |

### Columns Changing Nullability

| Column | Before | After | Reason |
|---|---|---|---|
| `gcp_project_id` | NOT NULL, UNIQUE | nullable, UNIQUE | GPU rows have no GCP project |
| `gke_cluster_name` | NOT NULL | nullable | GPU rows have no GKE cluster |
| `gke_region` | NOT NULL | nullable | GPU rows have no GKE region |

**Note**: SQLite allows multiple NULLs in a UNIQUE column (`gcp_project_id`), so multiple GPU rows coexist without conflict.

### Existing Rows on Migration
All existing rows are backfilled with `hardware_type = 'cpu'` and `lightning_ai_deployment_id = NULL`. Their `gcp_project_id`, `gke_cluster_name`, and `gke_region` values are preserved as-is.

### Full Column Listing (post-migration)

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `user_id` | TEXT | NOT NULL, INDEX |
| `hf_model_id` | TEXT | NOT NULL |
| `hf_model_display_name` | TEXT | NOT NULL |
| `hardware_type` | TEXT | NOT NULL, DEFAULT 'cpu' |
| `gcp_project_id` | TEXT | nullable, UNIQUE |
| `gke_cluster_name` | TEXT | nullable |
| `gke_region` | TEXT | nullable |
| `lightning_ai_deployment_id` | TEXT | nullable |
| `status` | TEXT | NOT NULL, DEFAULT 'queued' |
| `status_message` | TEXT | nullable |
| `endpoint_url` | TEXT | nullable |
| `created_at` | DATETIME | NOT NULL |
| `updated_at` | DATETIME | NOT NULL |
| `deleted_at` | DATETIME | nullable |

---

## 3. Entity: `LightningAICredentialStatus` (Pydantic response model)

Returned by `GET /api/lightning/credentials` and `POST /api/lightning/credentials`.

```python
class LightningAICredentialStatus(BaseModel):
    configured: bool
    validation_status: str | None       # "valid" | "invalid" | None
    validation_error_message: str | None
    last_validated_at: datetime | None
```

The API key itself is never included.

---

## 4. Entity: `LightningAICredentialRequest` (Pydantic request model)

Sent by `POST /api/lightning/credentials`.

```python
class LightningAICredentialRequest(BaseModel):
    api_key: str   # raw Lightning AI API key; encrypted before storage
```

---

## 5. Modified Entity: `DeployRequest`

```python
class DeployRequest(BaseModel):
    hf_model_id: str
    hardware_type: Literal["cpu", "gpu"]   # NEW — required, no default
    force: bool = False
```

`hardware_type` has no default — callers must supply it explicitly (FR-002).

---

## 6. Modified Entity: `Deployment` (response model)

```python
class Deployment(BaseModel):
    id: str
    hf_model_id: str
    hf_model_display_name: str
    hardware_type: str                    # NEW — "cpu" | "gpu"
    status: GkeDeploymentStatus
    status_message: str | None
    endpoint_url: str | None
    created_at: datetime
    updated_at: datetime
```

`DeploymentDetail` (extended response) gains `hardware_type` too. For CPU rows it also includes `gcp_project_id`, `gke_cluster_name`, `gke_region`, `gcp_console_url`. For GPU rows it includes `lightning_ai_deployment_id` instead.

---

## 7. State Transitions

### CPU Deployment (unchanged)
```
queued → deploying → running
               ↘ failed
deleting → deleted
lost (via status refresh)
```

### GPU Deployment (new)
```
queued → deploying → running
               ↘ failed   (Lightning AI reports error)
deleting → deleted         (after delete_app SDK call)
```

No `lost` state for GPU deployments (see spec Assumptions). The polling loop passes `hardware_type`-specific logic:
- CPU rows → check `provider.project_exists(gcp_project_id)` → flip to `lost` if gone
- GPU rows → check Lightning AI status → update `status` and `status_message` from SDK response; skip the `lost` check (Lightning AI manages its own lifecycle)

---

## 8. Service Layer: `LightningAICredentialsStore`

New service at `backend/src/services/lightning_ai_credentials_store.py`. Public interface:

```python
class LightningAICredentialsStore:
    async def save(self, *, user_id: str, api_key: str, provider: LightningAIProvider) -> LightningAICredentialStatus
    async def get_status(self, *, user_id: str) -> LightningAICredentialStatus
    async def get_decrypted_key(self, *, user_id: str) -> str | None
    async def delete(self, *, user_id: str) -> None
    async def record_key_invalid(self, *, user_id: str, error: Exception) -> None
```

---

## 9. Service Layer: `DeploymentStore` Changes

`DeploymentStore.create` gains a `hardware_type` parameter. When `hardware_type = "gpu"`:
- `gcp_project_id`, `gke_cluster_name`, `gke_region` are stored as `None`
- `lightning_ai_deployment_id` stays `None` until the orchestrator calls a new `store_lightning_deployment_id(deployment_id, lightning_ai_id)` helper after the SDK deploy call succeeds

New method:
```python
def store_lightning_deployment_id(self, *, deployment_id: str, lightning_ai_deployment_id: str) -> None
```

The concurrent-cap check and duplicate-model check in `create` are unchanged — they count all non-terminal rows regardless of `hardware_type`.

---

## 10. Service Layer: `DeploymentOrchestrator` Changes

`run_to_terminal` branches on `row.hardware_type` at the top:

```python
if row.hardware_type == "gpu":
    await self._run_lightning_ai(row, provider=lightning_ai_provider)
else:
    await self._run_gke(row, provider=gcp_provider)  # existing path, renamed internally
```

`_run_lightning_ai` flow:
1. Pre-flight: fetch and decrypt Lightning AI API key → fail fast if missing
2. Generate LitServe+vLLM script via `litserve_gpu.generate(hf_model_id)`
3. Write script to temp file
4. Call `lightning_ai_provider.deploy(hf_model_id, api_key)` → store returned `lightning_ai_deployment_id`
5. Status is polled by the existing `refresh_statuses` loop (modified to handle GPU rows)

`refresh_statuses` loop change: for GPU rows, call `lightning_ai_provider.get_status(deployment_id, api_key)` and update `status` + `status_message`. For CPU rows, the existing `project_exists` check runs unchanged.

`create_deployment` API endpoint receives both `GCPProvider` and `LightningAIProvider` via dependency injection. The orchestrator uses the appropriate one based on `hardware_type`.
