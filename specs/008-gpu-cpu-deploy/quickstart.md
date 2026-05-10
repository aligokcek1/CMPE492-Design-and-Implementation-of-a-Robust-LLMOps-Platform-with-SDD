# Quickstart: GPU / CPU Hardware Selector — Feature 008

**Branch**: `008-gpu-cpu-deploy`

---

## Prerequisites

```bash
# Required env vars
export LLMOPS_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
# Set once; existing .env file already has this for the dev environment

# New optional env var — disable Lightning AI status refresh in dev if no real key
export LLMOPS_DISABLE_STATUS_REFRESH=1  # set to disable both GCP and Lightning AI refresh loops
```

---

## Running the Backend

```bash
cd backend
pip install -e ".[dev]"          # picks up new: lightning-sdk, litserve
uvicorn src.main:app --reload
```

The DB schema migration runs automatically on startup (`ensure_schema()`). For a fresh install, the new `lightning_ai_credentials` table and updated `deployments` table are created directly. For an existing DB, the structural migration rebuilds `deployments` with nullable GKE columns and the new `hardware_type` / `lightning_ai_deployment_id` columns.

---

## Running the Frontend

```bash
cd frontend
pip install -e "."
streamlit run src/app.py
```

Open `http://localhost:8501`. You will see a new **⚡ Lightning AI** tab (6th tab) next to **☁️ GCP Credentials**.

---

## End-to-End: CPU Deployment (existing path)

1. Sign in with a Hugging Face token.
2. Go to **☁️ GCP Credentials** → save your service account key.
3. Go to **🚀 Deploy** → **Deploy a Public Repository**.
4. Enter a model ID (e.g. `Qwen/Qwen3-1.7B`) → click **Fetch Repository Info**.
5. Select **CPU** → click **🚀 Deploy to GKE**.
6. Monitor status in **📊 Deployments** — status messages reference GKE and CPU.

---

## End-to-End: GPU Deployment (new path)

1. Sign in with a Hugging Face token.
2. Go to **⚡ Lightning AI** → enter your Lightning AI API key → click **Save and validate**.
   - The backend calls the Lightning AI SDK to verify the key.
   - A green success banner confirms the key is valid.
3. Go to **🚀 Deploy** → **Deploy a Public Repository**.
4. Enter a model ID → click **Fetch Repository Info**.
5. Select **GPU** → click **🚀 Deploy to Lightning AI**.
6. Monitor status in **📊 Deployments** — status messages reference Lightning AI and GPU.
7. Once `running`, use the inference panel to send a chat completion request.
8. To stop: click **Delete** → the backend calls `lightning_ai_provider.delete()` → status transitions to `deleting → deleted`.

---

## Running Tests

```bash
cd backend
pytest tests/contract/                          # all contract tests (no cloud calls)
pytest tests/contract/test_lightning_ai_credentials_api.py  # new Lightning AI credential tests
pytest tests/contract/test_deployment_api.py    # includes new GPU deploy/delete tests
pytest                                          # full suite
```

**What the tests cover (GPU path)**:
- `test_lightning_ai_credentials_api.py`: GET (not configured), POST (valid key), POST (invalid key → 400), DELETE, POST after DELETE (re-save)
- `test_deployment_api.py` GPU additions: happy path (202 accepted), key missing (409 `lightning_credentials_missing`), key invalid (409 `lightning_credentials_invalid`), concurrent limit (409), duplicate model (409 + force=True), GPU delete (202 → deleted), inference proxy on GPU endpoint

```bash
cd frontend
pytest tests/integration/                       # Streamlit AppTest integration tests
```

**Frontend tests cover**: hardware selector default (disabled Deploy button), selecting CPU enables button, selecting GPU enables button, GPU deploy without Lightning AI key shows error banner directing to ⚡ tab.

---

## Key Files Changed / Added

| File | Change |
|---|---|
| `backend/src/db/models.py` | `LightningAICredentialsRow` (new); `DeploymentRow` extended |
| `backend/src/db/migrations.py` | Structural migration for `deployments`; new `lightning_ai_credentials` table |
| `backend/src/services/lightning_ai_credentials_store.py` | New — mirrors `credentials_store.py` |
| `backend/src/services/lightning_ai_provider.py` | New — abstract provider + real SDK impl |
| `backend/src/services/lightning_ai_fake_provider.py` | New — fake for tests |
| `backend/src/services/litserve_gpu.py` | New — `generate(hf_model_id) -> str` |
| `backend/src/services/deployment_store.py` | `hardware_type` param; GPU row creation; `store_lightning_deployment_id` |
| `backend/src/services/deployment_orchestrator.py` | Branch on `hardware_type`; `_run_lightning_ai`; updated `refresh_statuses` |
| `backend/src/api/lightning_ai_credentials.py` | New router — GET/POST/DELETE `/api/lightning/credentials` |
| `backend/src/api/deployment.py` | `hardware_type` in `DeployRequest`; GPU pre-flight check; GPU delete |
| `backend/src/models/lightning_ai_credentials.py` | New Pydantic models |
| `backend/src/models/deployment.py` | `hardware_type` on `DeployRequest` and `Deployment` response |
| `backend/src/main.py` | Register `lightning_ai_credentials.router` |
| `frontend/src/app.py` | Add ⚡ Lightning AI tab |
| `frontend/src/components/lightning_ai_credentials.py` | New — mirrors `gcp_credentials.py` |
| `frontend/src/components/deploy.py` | Hardware selector; GPU pre-flight error handling |
| `frontend/src/services/api_client.py` | Lightning AI credential API client functions |

---

## Environment Variables Reference

| Variable | Purpose | Required |
|---|---|---|
| `LLMOPS_ENCRYPTION_KEY` | Fernet key for encrypting credentials at rest (GCP + Lightning AI) | Yes |
| `LLMOPS_DISABLE_STATUS_REFRESH` | Set to `1` to skip background status polling (dev/test) | No |
