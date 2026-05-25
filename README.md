# LLMOps Platform

[![License: BSD-2-Clause](https://img.shields.io/badge/License-BSD%202--Clause-blue.svg)](LICENSE)

Event-driven pipeline for LLM lifecycle management: upload models, deploy to GKE (CPU) or Lightning AI (GPU), run inference, and monitor TTFT/throughput via Prometheus and Grafana.

**License:** [BSD 2-Clause](LICENSE) — Copyright (c) 2026, Ali GÖKÇEK

**Requirements:** Docker (recommended), or Python 3.11 for native development

## Quick start (Docker — recommended)

From the repo root, one command starts the backend, frontend, Prometheus, and Grafana. Secrets (`LLMOPS_ENCRYPTION_KEY`, `LLMOPS_GRAFANA_SIGNING_SECRET`) are generated automatically on first run and persisted in a Docker volume — no manual `.env` setup.

```bash
docker compose up -d --build
```

| Service    | URL |
|------------|-----|
| Dashboard  | http://localhost:8501 |
| API        | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Grafana    | http://localhost:3000 (`admin` / `admin`) |

Stop the stack:

```bash
docker compose down
```

To reset credentials and the SQLite database, remove volumes as well:

```bash
docker compose down -v
```

Local demo without real GCP (optional):

```bash
LLMOPS_USE_FAKE_GCP=1 docker compose up -d --build
```

Add that variable under `backend.environment` in `docker-compose.yml` if you want it permanently.

## Native development (without Docker)

### Setup (first time)

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

For deployment metrics and Grafana links (optional — export in the **backend** terminal before starting uvicorn):

```bash
export LLMOPS_GRAFANA_SIGNING_SECRET="$(python3.11 -c 'import secrets; print(secrets.token_hex(32))')"
export LLMOPS_PROMETHEUS_URL="http://localhost:9090"
export LLMOPS_PROMETHEUS_RELOAD_URL="http://localhost:9090/-/reload"
export LLMOPS_GRAFANA_PROMETHEUS_URL="http://prometheus:9090"
export LLMOPS_GRAFANA_URL="http://localhost:3000"
export LLMOPS_GRAFANA_ADMIN_USER="admin"
export LLMOPS_GRAFANA_ADMIN_PASSWORD="admin"
```

### Start (three terminals)

**Terminal 1 — monitoring**

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

**Terminal 2 — backend**

```bash
cd backend
source .venv/bin/activate
export LLMOPS_ENCRYPTION_KEY="<your-key>"
uvicorn src.main:app --reload
```

**Terminal 3 — frontend**

```bash
cd frontend
source .venv/bin/activate
streamlit run src/app.py
```

## Tests

```bash
cd backend && source .venv/bin/activate && pytest
cd frontend && source .venv/bin/activate && pytest
```

Contract tests use fake cloud providers — no GCP or Lightning AI calls.

## More detail

- Backend env vars, routes, GCP prerequisites: [`backend/README.md`](backend/README.md)
- Metrics monitoring E2E: [`specs/010-prometheus-grafana-monitoring/quickstart.md`](specs/010-prometheus-grafana-monitoring/quickstart.md)

## License

This project is licensed under the **BSD 2-Clause License**. See [`LICENSE`](LICENSE) for the full text.

Copyright (c) 2026, Ali GÖKÇEK

You may use, modify, and redistribute this software under the terms of the license, provided that Redistributions retain the copyright notice and disclaimer.
