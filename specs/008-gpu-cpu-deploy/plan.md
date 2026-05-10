# Implementation Plan: GPU / CPU Hardware Selector for Public Model Deployment

**Branch**: `008-gpu-cpu-deploy` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/008-gpu-cpu-deploy/spec.md`

## Summary

Add a GPU / CPU hardware selector to the **Deploy a Public Repository** flow. CPU keeps the existing GKE Autopilot + TGI-CPU path intact (zero breaking changes). GPU introduces a new Lightning AI managed-cloud path: the backend generates a LitServe + vLLM server script and submits it to [Lightning AI](https://lightning.ai/deploy) via the Lightning AI Python SDK. A new **⚡ Lightning AI** tab (mirrors the GCP Credentials tab) lets users manage their Lightning AI API key (Fernet-encrypted at rest, validated on save). The `deployments` table gains `hardware_type` and `lightning_ai_deployment_id` columns; the GKE-specific columns become nullable via a structural migration. The existing 3-deployment concurrent cap, status-polling loop, inference proxy, and duplicate-model guard all continue to work across both hardware types without modification.

---

## Technical Context

**Language/Version**: Python 3.11 (backend + frontend)

**Primary Dependencies**:
- Backend: FastAPI 0.135, Pydantic 2.12, SQLAlchemy 2.x, SQLite, `cryptography` (Fernet — existing), `httpx` (existing), `huggingface_hub` (existing), `litserve` (new — GPU server script generation), `lightning-sdk` (new — Lightning AI cloud API client)
- Frontend: Streamlit 1.55 (existing)

**Storage**: SQLite at `backend/data/llmops.db`. Extended with a new `lightning_ai_credentials` table and two new columns + schema migration on `deployments`. Fernet key from `LLMOPS_ENCRYPTION_KEY` (existing env var, reused for Lightning AI key encryption).

**Testing**: pytest, pytest-asyncio, httpx (existing). Real SQLite per test (temporary file). `FakeLightningAIProvider` mirrors `FakeGCPProvider` for contract tests — no real Lightning AI calls ever in `pytest`.

**Target Platform**: Linux server (backend), browser (Streamlit frontend).

**Performance Goals**:
- Hardware selector visible immediately after model info fetch (no extra API call)
- GPU deploy accepted (202) ≤ 2 s locally; actual Lightning AI provisioning time is Lightning AI's responsibility
- Status transitions reflected in UI ≤ 30 s of Lightning AI reporting them (same polling interval as GCP)

**Constraints**:
- `vllm_manifest.py` MUST NOT be renamed (legacy name, accepted tech debt)
- `gcp_project_id`, `gke_cluster_name`, `gke_region` on `DeploymentRow` must become nullable — requires structural SQLite migration (table rebuild), not a simple `ADD COLUMN`
- Lightning AI SDK: `lightning-sdk` package; machine type `Machine.T4` (NVIDIA T4, 16 GB VRAM — cheapest GPU tier); exact API surface confirmed in Phase 0 research
- No platform-side timeout for GPU deployments — rely entirely on Lightning AI terminal state

**Scale/Scope**: Student-project scale — single backend process, tens of users.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Clean & Readable Code | ✅ PASS | New modules mirror existing naming conventions (`lightning_ai_credentials_store.py`, `lightning_ai_provider.py`). No new helper layers. |
| II. Security First | ✅ PASS | Lightning AI API key encrypted with Fernet at rest; never returned from API (status endpoint returns `configured` + `validation_status` only). Key never logged. |
| III. Direct Framework & Library Usage | ✅ PASS | `lightning-sdk` client used directly; no wrapper class around it beyond the provider interface needed for test injection. `litserve` used directly for script generation. |
| IV. TDD Mandatory | ✅ PASS | All new endpoints (Lightning AI credentials GET/POST/DELETE, GPU deploy) written test-first using `FakeLightningAIProvider` and real SQLite. Red → green → refactor enforced per task. |
| V. Realistic & Comprehensive Testing | ✅ PASS | Real SQLite (temp file per test). `FakeLightningAIProvider` stubs only the network boundary; all DB, orchestrator, and routing logic runs real code. Contract tests cover happy path, key missing, key invalid, service error, concurrent limit, duplicate model for GPU path. |
| VI. Simplicity & Root Cause Resolution | ✅ PASS | CPU path untouched. GPU path reuses deployment record, status refresh loop, inference proxy endpoint, duplicate-model guard, and concurrent cap without modification. Structural migration for nullable columns is unavoidable (SQLite cannot ALTER column nullability additively) and is the root-cause fix rather than using dummy values. |

**Complexity Tracking** (constitution violations requiring justification):

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Structural SQLite migration (table rebuild for nullable columns) | `gcp_project_id` / `gke_cluster_name` / `gke_region` are `NOT NULL` in existing schema; GPU rows have no GCP project | SQLite cannot `ALTER COLUMN` to drop `NOT NULL`; dummy sentinel values would pollute the data model semantically and break the UNIQUE constraint on `gcp_project_id` for multiple GPU rows |
| New `lightning_ai_credentials` table (separate from `gcp_credentials`) | Lightning AI key has different fields (just an API key string vs. a full service-account JSON + billing ID) | Extending `gcp_credentials` would create nullable GCP-specific columns on every Lightning AI row and blur the credential model |

---

## Project Structure

### Documentation (this feature)

```text
specs/008-gpu-cpu-deploy/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
├── contracts/
│   └── openapi.yaml     ← Phase 1 output
└── checklists/
    └── requirements.md  ← from /speckit-specify
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── main.py                                      # MODIFIED: register lightning_ai_credentials router
│   ├── api/
│   │   ├── lightning_ai_credentials.py              # NEW: GET/POST/DELETE /api/lightning/credentials
│   │   └── deployment.py                            # MODIFIED: hardware_type in DeployRequest routing
│   ├── models/
│   │   ├── lightning_ai_credentials.py              # NEW: Pydantic request/response models
│   │   └── deployment.py                            # MODIFIED: hardware_type field on DeployRequest
│   ├── db/
│   │   ├── models.py                                # MODIFIED: LightningAICredentialsRow + DeploymentRow cols
│   │   └── migrations.py                            # MODIFIED: structural migration + new additive migrations
│   └── services/
│       ├── lightning_ai_credentials_store.py        # NEW: mirrors credentials_store.py for Lightning AI key
│       ├── lightning_ai_provider.py                 # NEW: abstract provider + real SDK implementation
│       ├── lightning_ai_fake_provider.py            # NEW: fake for contract tests
│       ├── litserve_gpu.py                          # NEW: generates LitServe+vLLM server script string
│       ├── deployment_store.py                      # MODIFIED: hardware_type param, GPU row creation
│       └── deployment_orchestrator.py               # MODIFIED: branch on hardware_type for GPU path
└── tests/contract/
    ├── conftest.py                                  # MODIFIED: FakeLightningAIProvider fixture
    ├── test_lightning_ai_credentials_api.py         # NEW: credential CRUD + validation tests
    └── test_deployment_api.py                       # MODIFIED: GPU deploy happy/error/delete tests

frontend/
├── src/
│   ├── app.py                                       # MODIFIED: add ⚡ Lightning AI tab (6th tab)
│   ├── components/
│   │   ├── lightning_ai_credentials.py              # NEW: mirrors gcp_credentials.py component
│   │   └── deploy.py                                # MODIFIED: hardware selector + GPU error handling
│   └── services/
│       └── api_client.py                            # MODIFIED: Lightning AI credential API calls
└── tests/integration/
    └── test_workflow.py                             # MODIFIED: GPU hardware selector + deploy scenarios
```

**Structure Decision**: Web application (backend + frontend) — Option 2 from the plan template, consistent with all prior features.

---

## Phase 0: Research

See [`research.md`](./research.md) — all NEEDS CLARIFICATION items resolved there.

---

## Phase 1: Design

See:
- [`data-model.md`](./data-model.md) — entity definitions, schema changes, state transitions
- [`contracts/openapi.yaml`](./contracts/openapi.yaml) — new and modified HTTP endpoints
- [`quickstart.md`](./quickstart.md) — how to run and test the feature end-to-end
