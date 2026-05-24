# LLMOps Platform

Event-driven pipeline for LLM lifecycle management: upload models, deploy to GKE (CPU) or Lightning AI (GPU), run inference, and monitor TTFT/throughput via Prometheus and Grafana.

**Requirements:** Python 3.11, Docker (optional, for monitoring stack)

## Setup (first time)

From the repo root:

```bash
# Backend
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

Generate and save a Fernet key (reuse the same value on every restart):

```bash
export LLMOPS_ENCRYPTION_KEY="$(python3.11 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

For deployment metrics and Grafana links (optional — export in the **backend** terminal before starting uvicorn, not in the Docker Compose terminal):

```bash
export LLMOPS_GRAFANA_SIGNING_SECRET="$(python3.11 -c 'import secrets; print(secrets.token_hex(32))')"
export LLMOPS_PROMETHEUS_URL="http://localhost:9090"          # backend (host) → Prometheus API
export LLMOPS_PROMETHEUS_RELOAD_URL="http://localhost:9090/-/reload"  # backend tells Prometheus to pick up new scrape jobs
export LLMOPS_GRAFANA_PROMETHEUS_URL="http://prometheus:9090" # Grafana (Docker) → Prometheus
export LLMOPS_GRAFANA_URL="http://localhost:3000"
export LLMOPS_GRAFANA_ADMIN_USER="admin"
export LLMOPS_GRAFANA_ADMIN_PASSWORD="admin"
```

## Start

Use three terminals (activate the matching venv in each).

**Terminal 1 — monitoring (optional)**

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Prometheus: http://localhost:9090 · Grafana: http://localhost:3000 (`admin` / `admin`)

**Terminal 2 — backend**

```bash
cd backend
source .venv/bin/activate
export LLMOPS_ENCRYPTION_KEY="<your-key>"   # required
# If using monitoring, also export the vars from Setup above (including LLMOPS_PROMETHEUS_RELOAD_URL)
uvicorn src.main:app --reload
```

API: http://localhost:8000 · Metrics: http://localhost:8000/metrics

**Terminal 3 — frontend**

```bash
cd frontend
source .venv/bin/activate
streamlit run src/app.py
```

UI: http://localhost:8501

## Tests

```bash
cd backend && source .venv/bin/activate && pytest
cd frontend && source .venv/bin/activate && pytest
```

Contract tests use fake cloud providers — no GCP or Lightning AI calls.

## Local demo without cloud

```bash
export LLMOPS_USE_FAKE_GCP=1
```

Then start the backend as above. Real deployments still need GCP and/or Lightning AI credentials configured in the UI.

## More detail

- Backend env vars, routes, GCP prerequisites: [`backend/README.md`](backend/README.md)
- Metrics monitoring E2E: [`specs/010-prometheus-grafana-monitoring/quickstart.md`](specs/010-prometheus-grafana-monitoring/quickstart.md)
