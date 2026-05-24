# Quickstart: Deployment Metrics Monitoring — Feature 010

**Branch**: `010-prometheus-grafana-monitoring`

---

## Prerequisites

```bash
# Existing required env var
export LLMOPS_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# New monitoring env vars
export LLMOPS_GRAFANA_SIGNING_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export LLMOPS_PROMETHEUS_URL="http://localhost:9090"
export LLMOPS_GRAFANA_PROMETHEUS_URL="http://prometheus:9090"
export LLMOPS_GRAFANA_URL="http://localhost:3000"
export LLMOPS_GRAFANA_ADMIN_USER="admin"
export LLMOPS_GRAFANA_ADMIN_PASSWORD="admin"
export LLMOPS_GRAFANA_LINK_TTL_SECONDS="900"   # 15 minutes

# Disable monitoring provisioning in unit tests (set automatically in conftest)
# export LLMOPS_METRICS_DISABLED=1
```

---

## Start the Monitoring Stack

From repo root:

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Verify:
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login `admin` / `admin`)

---

## Run the Backend

```bash
cd backend
pip install -e ".[dev]"          # picks up prometheus-client
uvicorn src.main:app --reload
```

The backend exposes proxy metrics at `GET /metrics` and registers per-deployment scrape jobs when deployments reach `running`.

---

## Run the Frontend

```bash
cd frontend
pip install -e "."
streamlit run src/app.py
```

Open http://localhost:8501.

---

## End-to-End: View Metrics for a Running Deployment

1. Sign in with a Hugging Face token.
2. Deploy a model (CPU or GPU) using the existing **Deploy to Cloud** flow.
3. Wait until the deployment status is **Running**.
4. Send at least one inference request via the **Run inference** panel.
5. In **Deployments**, expand the **📈 Metrics** panel on the running deployment.
6. Confirm you see:
   - **TTFT** summary + trend chart
   - **Throughput** summary + trend chart
   - **Hardware** charts (CPU/memory for CPU; GPU may show N/A for Lightning AI)
7. Click **Open in Grafana** → browser opens signed redirect → Grafana dashboard scoped to that deployment.

---

## End-to-End: Verify Post-Delete Behavior

1. Delete a running deployment.
2. Confirm the **Metrics** panel and **Open in Grafana** button disappear immediately.
3. Confirm `GET /api/deployments/{id}/metrics` returns **404** for the deleted deployment.
4. (Operator) Prometheus still retains time-series until decommission job runs (≥ 7 days).

---

## Running Tests

```bash
cd backend
pytest tests/contract/test_metrics_api.py       # new metrics + grafana link tests
pytest tests/contract/test_deployment_api.py    # inference metrics recording
pytest tests/contract/                          # full contract suite (fakes — no Prometheus/Grafana)
```

```bash
cd frontend
pytest tests/integration/                       # metrics panel render scenarios
```

**Contract test coverage (metrics)**:
- Running deployment → 200 with TTFT/throughput series
- No inference traffic → 200 with `empty: true`
- Deleted / non-running deployment → 404
- Foreign user's deployment → 403
- Prometheus unavailable → explicit error (503 or 200 with `error` field)
- Grafana link mint → 200 with `redirect_url` + `expires_at`
- Expired signed token on redirect → 403
- GPU deployment with no GPU hardware series → `gpu_utilization.available: false`

---

## Key Files Added / Modified

| File | Change |
|---|---|
| `docker-compose.monitoring.yml` | Prometheus + Grafana dev stack |
| `backend/monitoring/prometheus.yml` | Base Prometheus config |
| `backend/monitoring/grafana/dashboards/deployment-metrics.json` | Dashboard template |
| `backend/src/db/models.py` | `DeploymentMonitoringRow` |
| `backend/src/services/metrics_recorder.py` | Proxy-side Prometheus metrics |
| `backend/src/services/metrics_query.py` | PromQL → API response |
| `backend/src/services/monitoring_orchestrator.py` | Provision/decommission lifecycle |
| `backend/src/services/prometheus_provisioner.py` | Scrape job management |
| `backend/src/services/grafana_provisioner.py` | Grafana API provisioning |
| `backend/src/services/grafana_signed_url.py` | HMAC signed redirect tokens |
| `backend/src/api/metrics.py` | Metrics + Grafana endpoints |
| `backend/src/services/inference_proxy.py` | TTFT/token instrumentation |
| `backend/src/services/deployment_orchestrator.py` | Trigger monitoring on running/delete |
| `frontend/src/components/deployment_metrics.py` | Native Streamlit metrics panel |
| `frontend/src/components/deployments_list.py` | Embed metrics for running deployments |
| `frontend/src/services/api_client.py` | Metrics API client functions |

---

## Environment Variables Reference

| Variable | Purpose | Required |
|---|---|---|
| `LLMOPS_ENCRYPTION_KEY` | Fernet key (existing) | Yes |
| `LLMOPS_GRAFANA_SIGNING_SECRET` | HMAC secret for Grafana signed links | Yes (when metrics enabled) |
| `LLMOPS_PROMETHEUS_URL` | Prometheus HTTP API base URL | Yes (when metrics enabled) |
| `LLMOPS_GRAFANA_URL` | Grafana HTTP API + redirect target | Yes (when metrics enabled) |
| `LLMOPS_GRAFANA_ADMIN_USER` | Grafana API admin user | Yes (when metrics enabled) |
| `LLMOPS_GRAFANA_ADMIN_PASSWORD` | Grafana API admin password | Yes (when metrics enabled) |
| `LLMOPS_GRAFANA_LINK_TTL_SECONDS` | Signed link TTL (default 900) | No |
| `LLMOPS_METRICS_DISABLED` | Set to `1` to skip provisioning (tests) | No |
| `LLMOPS_DISABLE_STATUS_REFRESH` | Existing — disables status polling | No |
