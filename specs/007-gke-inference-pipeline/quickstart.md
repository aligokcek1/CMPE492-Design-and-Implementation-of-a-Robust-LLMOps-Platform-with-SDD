# Quickstart: GKE Inference Pipeline

## Prerequisites

- Existing platform dev setup working (features 004–006).
- A GCP account with **billing enabled** and a service account holding:
  - `roles/resourcemanager.projectCreator`
  - `roles/billing.user`
  - `roles/serviceusage.serviceUsageAdmin`
  - `roles/container.admin`
  - `roles/resourcemanager.projectDeleter`
- A HuggingFace account and read-access token for gated models (optional for fully-open models like Qwen3).

## One-time setup

```bash
cd backend

uv pip install -r requirements.txt

python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > .encryption_key
export LLMOPS_ENCRYPTION_KEY=$(cat .encryption_key)

mkdir -p data
```

> Keep `.encryption_key` out of git. Losing it means every stored credential becomes unrecoverable (which is actually the intended failure mode — users will just re-enter credentials).

## Run the backend

```bash
cd backend
export LLMOPS_ENCRYPTION_KEY=$(cat .encryption_key)
uvicorn src.main:app --reload
```

## Run the frontend

```bash
cd frontend
streamlit run src/app.py
```

## Configure GCP credentials

1. Log in to the platform via the existing HuggingFace login flow.
2. Open the new **GCP Credentials** tab.
3. Paste your service-account JSON key and billing account ID (format `billingAccounts/XXXXXX-YYYYYY-ZZZZZZ`).
4. Click **Save**. The platform validates the key against real GCP before persisting. You should see a green "valid" badge with the service-account email and parent project displayed.

## Deploy a public model

1. Open the **Models** tab, search for and select a public HF model that fits on 24 GB VRAM. Recommended first pick: `Qwen/Qwen3-1.7B`.
2. Click **Deploy**.
3. The **Deployments** tab shows the record in `queued`, then `deploying`. Expect 8–25 minutes for the first deployment (project creation + cluster bring-up + model weights download).
4. Once `running`, the endpoint URL appears (e.g. `http://34.123.45.67:80`).

## Call inference

### From the UI

Open the deployment → type into the **Inference Panel** → Send. Responses appear within 120 s (hard timeout).

### From outside

```bash
curl http://34.123.45.67:80/v1/chat/completions \
  -X POST -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-1.7B",
    "messages": [{"role":"user","content":"Describe a GPU in one sentence."}]
  }'
```

## Delete a deployment

**Deployments** tab → click **Delete** on the row → confirm. The platform tears down the whole GCP project, ensuring zero orphaned cloud resources. Expect deletion to complete within ~10 minutes (SC-003).

## Testing

```bash
cd backend && pytest                      # Contract + integration tests (FakeGCPProvider — zero cloud calls)
cd frontend && pytest                     # Streamlit AppTest integration

LLMOPS_K8S_DRYRUN_KUBECONFIG=~/.kube/scratch-config \
  cd backend && pytest tests/dryrun       # Opt-in manifest validation via Kubernetes server-side dry-run.
                                          # Requires a scratch cluster (kind/minikube/etc).
                                          # Uses dry_run=["All"] — creates zero real resources.
                                          # Still does NOT call any GCP API.
```

> Tests never run against real GCP. The Resource Manager, Billing, and GKE cluster-create APIs have no dry-run flag, so there is no zero-side-effect way to exercise them — the `FakeGCPProvider` is the only test path for those boundaries. Kubernetes, which does support dry-run, gets an opt-in suite above.
