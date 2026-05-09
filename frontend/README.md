# LLMOps Platform — Frontend

Streamlit dashboard for the LLMOps Platform. Ties the FastAPI backend together
with a tab-based UI for uploading models, selecting existing ones, deploying
them, managing deployments, and configuring GCP credentials.

## Tabs

| Tab | Feature | What you can do |
|---|---|---|
| 📤 **Upload Model** | 004 / 005 | Upload a local folder or files to a new Hugging Face repo. |
| 🔍 **Select Existing** | 004 | Pick a model you already own on HuggingFace. |
| 🚀 **Deploy** | 005 + **007** | For personal models: mocked CPU/GPU deploy. For public models: real deployment to GKE Autopilot on a cheapest-L4 GPU via vLLM. |
| 📊 **Deployments** | **007 (US3 + US4 + US5)** | List your active deployments, watch status, delete them, dismiss "lost" records, and run inference inline (120s timeout). |
| ☁️ **GCP Credentials** | **007 (US1)** | Save/validate/delete your GCP service-account key + billing account. Never leaves the server in plaintext; encrypted at rest. |

A persistent warning banner appears above every tab when your stored GCP
credentials are marked invalid (FR-015) — new deployments and deletions are
blocked, but running deployments are unaffected.

## Setup

```bash
cd frontend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run src/app.py
```

Point this at a running backend (default `http://localhost:8000`).

## Tests

```bash
pytest
```
