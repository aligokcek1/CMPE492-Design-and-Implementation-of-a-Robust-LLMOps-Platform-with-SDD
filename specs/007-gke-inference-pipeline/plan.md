# Implementation Plan: GKE Inference Pipeline for Public HuggingFace Models

**Branch**: `007-gke-inference-pipeline` | **Date**: 2026-04-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-gke-inference-pipeline/spec.md`

## Summary

Replace the current mock GCP deployment path with a real pipeline that provisions a dedicated GCP project per deployment, spins up a GKE Autopilot cluster, and serves a public HuggingFace text-generation model behind a vLLM OpenAI-compatible endpoint. Users enter GCP credentials once via the dashboard; the platform validates them, persists them encrypted, and orchestrates project creation, cluster bring-up, vLLM deployment, teardown, and an in-UI inference proxy. Personal-model deployments continue to use the existing mock path. Deployments and credentials survive backend restarts via SQLite persistence.

## Technical Context

**Language/Version**: Python 3.11 (backend + frontend)
**Primary Dependencies**:
- Backend: FastAPI 0.135, Pydantic 2.12, SQLAlchemy 2.x, SQLite (stdlib driver), `cryptography` (Fernet) for SA-JSON encryption at rest, `google-cloud-resource-manager`, `google-cloud-billing`, `google-cloud-container` (GKE), `google-auth`, `kubernetes` (Python client), `huggingface_hub` (already present), `httpx` (already present) for the inference proxy
- Frontend: Streamlit 1.55 (already present)
**Storage**: SQLite file at `backend/data/llmops.db` (2 tables: `gcp_credentials`, `deployments`). Service-account JSON encrypted with Fernet; key read from `LLMOPS_ENCRYPTION_KEY` env var.
**Testing**: pytest, pytest-asyncio, httpx (existing). Realistic SQLite via temporary file per test. GCP boundary stubbed by a `FakeGCPProvider` implementing the same interface as the real provider (see Complexity Tracking for rationale). **Tests never call real cloud services.** An opt-in suite in `tests/dryrun/` validates generated vLLM Kubernetes manifests against a real API server using `kubernetes` client's `dry_run=["All"]` — gated on `LLMOPS_K8S_DRYRUN_KUBECONFIG`, skipped by default.
**Target Platform**: Linux server (backend), browser (Streamlit frontend). Deployed workloads run on GKE Autopilot, region `us-central1`.
**Project Type**: Web application (backend + frontend, already established)
**Performance Goals**:
- Deploy click → "deploying" status visible ≤2 s (local)
- Real GKE bring-up + vLLM readiness: 8–25 min for Qwen3-class small models (network-bound on container+weights pull)
- In-UI inference proxy: 120 s hard timeout (SC-008)
- Deployment list refresh reflects GCP state ≤30 s (SC-002)
**Constraints**:
- Cheapest GPU viable for small text-gen models: **NVIDIA L4 (24 GB VRAM)** on a `g2-standard-8` equivalent Autopilot pod spec
- Hard cap: 3 concurrent running deployments per user (FR-013)
- Target model size: Qwen3-0.6B / 1.7B / 4B / 8B (and equivalent) — models fitting in 24 GB VRAM at bf16 or fp8 quantization
- Inference endpoint URL acts as an implicit secret; never shown to non-owners
**Scale/Scope**: Student-project scale — single backend process, tens of users, tens of lifetime deployments. Not multi-region, no HA on the control plane itself.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Clean & Readable Code | PASS | No new wrappers; module names describe their responsibility. |
| II. Security First | PASS | SA JSON encrypted at rest with Fernet; never returned from the API; `.gitignore` covers the SQLite DB; API only returns credential *status*, never the key. |
| III. Direct Framework & Library Usage | PASS | Use `google-cloud-*` clients and the official `kubernetes` Python client directly. No custom abstraction around them beyond a single provider interface used to inject a test fake. |
| IV. TDD Mandatory | PASS | All new endpoints are written test-first against a `FakeGCPProvider`; end-to-end flow tested with a real SQLite file. Red → green → refactor enforced. |
| V. Realistic & Comprehensive Testing | PARTIAL — justified in Complexity Tracking | Real SQLite used. The GCP boundary is swapped for `FakeGCPProvider` (no cloud calls ever in `pytest`). An opt-in suite `tests/dryrun/` validates generated vLLM manifests via Kubernetes server-side dry-run (`dry_run=["All"]`) against a user-supplied scratch kubeconfig — adds realism without creating any real resource. |
| VI. Simplicity & Root Cause Resolution | PASS | No Terraform added (would introduce state files and a second toolchain). Single orchestrator module drives the pipeline with explicit state transitions. |

## Project Structure

### Documentation (this feature)

```text
specs/007-gke-inference-pipeline/
├── plan.md               # This file
├── research.md           # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── openapi.yaml      # Phase 1 output
└── checklists/
    └── requirements.md   # From /speckit.specify
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── main.py                              # existing; register new routers
│   ├── api/
│   │   ├── gcp_credentials.py               # NEW — POST/GET/DELETE /api/gcp/credentials
│   │   ├── deployment.py                    # EXTENDED — real public deploy + list/get/delete/inference
│   │   └── deployment_public.py             # [split of existing public-repo endpoints if needed]
│   ├── models/
│   │   ├── gcp_credentials.py               # NEW — Pydantic request/response models
│   │   └── deployment.py                    # EXTENDED — add deployment status, endpoint, GCP project id
│   ├── db/
│   │   ├── __init__.py                      # NEW — engine + session factory
│   │   ├── models.py                        # NEW — SQLAlchemy ORM models
│   │   └── migrations.py                    # NEW — idempotent create_all on startup (lightweight)
│   ├── services/
│   │   ├── credentials_store.py             # NEW — CRUD for GCPCredentials, Fernet encrypt/decrypt
│   │   ├── deployment_store.py              # NEW — CRUD for Deployments
│   │   ├── gcp_provider.py                  # NEW — interface + real impl (Projects/Billing/GKE clients)
│   │   ├── gcp_fake_provider.py             # NEW — in-memory fake for tests
│   │   ├── kube_client.py                   # NEW — thin kubernetes-client helpers (apply, delete, watch)
│   │   ├── vllm_manifest.py                 # NEW — generator for the qwen3-style vLLM Deployment + Service
│   │   ├── deployment_orchestrator.py       # NEW — async state machine: queued → deploying → running/failed
│   │   ├── inference_proxy.py               # NEW — httpx forwarder with 120s timeout
│   │   └── mock_gcp.py                      # existing; retained for personal-model mock (FR-010)
└── tests/
    ├── contract/
    │   ├── test_gcp_credentials_api.py      # NEW
    │   └── test_deployment_api.py           # EXTENDED (add real-deploy + inference proxy cases)
    ├── integration/
    │   ├── test_deployment_orchestrator.py  # NEW — full state machine with FakeGCPProvider
    │   └── test_credentials_encryption.py   # NEW — round-trip through a real SQLite file
    └── dryrun/
        └── test_vllm_manifest_dryrun.py     # NEW — gated by LLMOPS_K8S_DRYRUN_KUBECONFIG; validates manifests via kubernetes dry_run=["All"]. Never calls GCP. Skipped by default.

frontend/
├── src/
│   ├── app.py                               # existing; add Credentials + Deployments tabs
│   ├── components/
│   │   ├── gcp_credentials.py               # NEW — credential entry form, validation feedback
│   │   ├── deployments_list.py              # NEW — list view with status badges + delete + dismiss-lost
│   │   └── inference_panel.py               # NEW — prompt input, 120s countdown, response display
│   └── services/
│       └── api_client.py                    # EXTENDED — new client methods for credentials + real deploy + inference
└── tests/
    └── integration/
        └── test_gke_deploy_workflow.py      # NEW — AppTest-driven flow using FakeGCPProvider via backend
```

**Structure Decision**: Web application layout (already established by feature 006). This feature adds a `backend/src/db/` package for the first time and a provider-interface pattern in `services/` so the GCP boundary can be swapped for a fake without introducing wrappers over the cloud libraries themselves.

## Phase 0 — Research

See [research.md](./research.md). All NEEDS CLARIFICATION items are resolved there:

- GKE Autopilot vs Standard → Autopilot
- Cheapest GPU for Qwen3-class inference → NVIDIA L4 (24 GB VRAM), `us-central1`
- vLLM container image → `vllm/vllm-openai:latest` (OpenAI-compatible server built in)
- GCP project provisioning flow → Resource Manager + Billing + `container.googleapis.com` enablement
- Public endpoint shape → `Service type=LoadBalancer` on port 80→8000 (simple, stable IP, no extra ingress cost)
- Encrypted-at-rest credential storage → `cryptography.fernet.Fernet` with key from env
- Inference timeout behavior → httpx client-side timeout 120 s; server-side no timeout override on vLLM

## Phase 1 — Design & Contracts

### Data Model

See [data-model.md](./data-model.md).

Two new tables: `gcp_credentials` (one row per platform user) and `deployments` (zero-or-many per user). Explicit state machine on `deployments.status`: `queued → deploying → running → (deleting | lost) → deleted | failed`.

### Contracts

See [contracts/openapi.yaml](./contracts/openapi.yaml). New/changed endpoints:

- `POST /api/gcp/credentials` — save or replace credentials (validates before persist)
- `GET /api/gcp/credentials` — status only (never returns the key)
- `DELETE /api/gcp/credentials` — only allowed when user has no active deployments
- `POST /api/deployments` — initiate a real public-model deployment (body carries HF model id + optional `force=true` for duplicate-model confirm)
- `GET /api/deployments` — list caller's deployments
- `GET /api/deployments/{id}` — deployment detail including endpoint URL
- `DELETE /api/deployments/{id}` — triggers GCP project teardown
- `POST /api/deployments/{id}/dismiss` — only valid for `lost` status
- `POST /api/deployments/{id}/inference` — platform-proxied inference call (OpenAI chat-completions passthrough, 120 s timeout)

### Quickstart

See [quickstart.md](./quickstart.md) — covers: install new Python deps, set `LLMOPS_ENCRYPTION_KEY`, run backend, configure GCP credentials, deploy Qwen3-0.6B, call inference, delete.

### Agent Context

Agent-specific context file updated via `.specify/scripts/bash/update-agent-context.sh cursor-agent` at the end of this plan run.

## Phase 2 — Task breakdown

*Not produced by `/speckit.plan`.* Run `/speckit.tasks` next.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `FakeGCPProvider` for tests (deviates from Principle V "prefer real services") | Real GCP project + GKE bring-up costs $$ and takes 15–30 min per test. Resource Manager / Billing / GKE create APIs have **no dry-run flag**, so there is no zero-side-effect way to exercise them. Kubernetes, which *does* support server-side dry-run, is covered by an opt-in `tests/dryrun/` suite gated on `LLMOPS_K8S_DRYRUN_KUBECONFIG`. | Running real GCP in CI would make the suite slow, flaky, and expensive (order of dollars per run, multi-hour total runtime). "Live GCP" smoke tests were explicitly rejected — they would create real billable resources. The provider-interface pattern keeps production code direct (no wrapper layer); the fake only substitutes at the dependency-injection point. |
| Adding SQLite + SQLAlchemy (new storage layer vs previous in-memory session store) | Directly required by clarification: credentials + deployment records MUST survive backend restart. Losing the mapping between a platform deployment record and its GCP project ID would orphan real cloud resources. | In-memory only was the prior convention (feature 006). It is incompatible with managing real, long-lived cloud projects — the user could lose the ability to delete a project they created. |

## Re-check after Phase 1

All gates still PASS. The provider-interface + SQLite additions do not introduce wrappers over libraries (SQLAlchemy is used directly; google-cloud clients are used directly inside `GCPProvider`). No new `NEEDS CLARIFICATION` markers introduced during design.
