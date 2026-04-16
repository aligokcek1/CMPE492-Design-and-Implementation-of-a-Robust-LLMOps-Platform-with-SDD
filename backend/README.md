# LLMOps Platform — Backend

FastAPI service that powers the LLMOps Platform dashboard. Handles Hugging Face
authentication, file/folder uploads, personal-repo mock deployments, and — as of
feature **007** — real public-model inference deployments on GKE.

## Setup

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

| Name | Required | Purpose |
|------|----------|---------|
| `LLMOPS_ENCRYPTION_KEY` | **yes (feature 007)** | Fernet key used to encrypt GCP service-account JSON at rest in `backend/data/llmops.db`. Must remain stable across restarts — losing it invalidates every saved credential. |
| `LLMOPS_K8S_DRYRUN_KUBECONFIG` | no | Path to a scratch kubeconfig used by the opt-in `tests/dryrun/` suite to validate generated vLLM manifests via server-side `dry_run=["All"]`. When unset, the suite is skipped. |

### Generate a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Export it before running the server:

```bash
export LLMOPS_ENCRYPTION_KEY=<key-from-above>
```

## Run the dev server

```bash
uvicorn src.main:app --reload
```

The SQLite database is created on first startup at `backend/data/llmops.db` and
is git-ignored. Deleting the file resets all credentials and deployment records.

## Tests

```bash
pytest                # contract + integration, all using FakeGCPProvider
```

**No test in this repository calls real GCP.** See the Testing Policy in
`.cursor/rules/specify-rules.mdc`.

To run the opt-in Kubernetes dry-run suite:

```bash
export LLMOPS_K8S_DRYRUN_KUBECONFIG=/path/to/scratch-kubeconfig
pytest tests/dryrun/
```
