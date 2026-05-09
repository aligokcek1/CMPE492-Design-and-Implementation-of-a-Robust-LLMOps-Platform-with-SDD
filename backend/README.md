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
| `LLMOPS_USE_FAKE_GCP` | no | Set to `1` to force the in-memory `FakeGCPProvider` even outside pytest (useful for local UI demos without a real GCP account). Never touches real cloud APIs. |
| `LLMOPS_DATABASE_URL` | no | Override the default SQLite path (`backend/data/llmops.db`). Tests use this to point at a per-test temp file. |
| `LLMOPS_DISABLE_STATUS_REFRESH` | no | Set to `1` to skip the background 30s status-refresh loop. Useful in test environments or when you only care about request-path behaviour. |
| `LLMOPS_K8S_DRYRUN_KUBECONFIG` | no | Path to a scratch kubeconfig used by the opt-in `tests/dryrun/` suite to validate generated CPU inference manifests via server-side `dry_run=["All"]`. When unset, the suite is skipped. |

## Routes added by feature 007

| Method | Path | Purpose |
|---|---|---|
| `GET`    | `/api/gcp/credentials`                    | Return SA email + billing ID status (never the key). |
| `POST`   | `/api/gcp/credentials`                    | Save/replace + validate the user's GCP credentials. |
| `DELETE` | `/api/gcp/credentials`                    | Remove credentials (blocked while active deployments exist). |
| `POST`   | `/api/deployments`                        | Start a real public-model deployment to GKE (202 + state machine). |
| `GET`    | `/api/deployments`                        | List the caller's deployments. |
| `GET`    | `/api/deployments/{id}`                   | Full detail incl. GCP project + console URL. |
| `DELETE` | `/api/deployments/{id}`                   | Tear down the dedicated GCP project for the deployment. |
| `POST`   | `/api/deployments/{id}/dismiss`           | Hard-delete a `lost` record (project gone out-of-band). |
| `POST`   | `/api/deployments/{id}/inference`         | OpenAI-style chat proxy (backed by CPU TGI `/generate`) with a hard 120s read timeout (SC-008). |

The legacy `/api/deployment/mock` endpoint is preserved for **personal-repo** deployments per FR-010.

### Generate a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save it once, then reuse the same value for every backend restart.
If this key changes, previously saved GCP credentials in `llmops.db` become
undecryptable.

Export it before running the server:

```bash
export LLMOPS_ENCRYPTION_KEY=<key-from-above>
```

## Run the dev server

```bash
uvicorn src.main:app --reload
```

## One-liner (first run only)

Use this only the very first time, then persist the generated key somewhere
safe (shell profile, `.env`, secret manager) and reuse it.

```bash
export LLMOPS_ENCRYPTION_KEY="$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")" && uvicorn src.main:app --reload
```

The SQLite database is created on first startup at `backend/data/llmops.db` and
is git-ignored. Deleting the file resets all credentials and deployment records.

## GCP prerequisites for real deployments

Service accounts are **not allowed to create GCP projects without a parent**.
Before the **🚀 Deploy** tab will work against real GCP, your service account
needs:

1. An **Organization or Folder** it can create projects under (format:
   `organizations/<NUMERIC-ID>` or `folders/<NUMERIC-ID>`). You paste this into
   the "Deployment parent" field in the **☁️ GCP Credentials** tab.
2. The following IAM roles on that Organization/Folder:
   - `roles/resourcemanager.projectCreator`
   - `roles/billing.user` (so it can attach a billing account to the new project)
3. `roles/serviceusage.serviceUsageAdmin` (to enable Compute / GKE / Billing APIs on each new project).
4. `roles/container.admin` (to create GKE Autopilot clusters).

You can verify your org/folder id via:

```bash
gcloud organizations list
gcloud resource-manager folders list --organization <ORG-ID>
```

Free-trial accounts without an organization can't use service-account-driven
project creation — you'll need to set up an Organization resource first, or
use personal credentials (not recommended for a long-running server).

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
