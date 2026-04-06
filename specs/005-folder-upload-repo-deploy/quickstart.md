# Quickstart: Folder Upload and Public Repository Deployment

This guide explains the new capabilities added in feature 005 and how to exercise them locally.
The environment setup is identical to feature 004 — if you already have the virtualenvs and servers running, skip to [New Features](#new-features).

## Prerequisites

- Python 3.11+
- A Hugging Face account with a **write-access** token (for folder upload).
- A read-access or write-access token is sufficient for the public repo metadata fetch and mock deploy.

## Backend Setup (FastAPI)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## Frontend Setup (Streamlit)

```bash
cd frontend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/app.py
```

## Running Tests

```bash
# Backend contract + unit tests
cd backend && pytest

# Frontend integration tests
cd frontend && pytest
```

---

## New Features

### 1. Multi-Folder Upload

The **Upload Model** tab now supports uploading multiple folder groups into a single Hugging Face repository.

**Steps**:
1. Sign in with your HF token.
2. Go to the **Upload Model** tab.
3. Enter the **Target Repository ID** (e.g., `alice/my-model`).
4. In the **Folder Groups** section, enter a name for your first folder (e.g., `weights`) and select its files using the file picker.
5. Click **+ Add Folder** to add additional folders (e.g., `tokenizer`, `config`).
6. Each folder name must be unique and non-empty. The upload button is disabled until all groups are valid.
7. Click **Upload to Hugging Face** to start the batch upload.

**What happens**: All selected files are sent to the backend with their folder name as a path prefix (e.g., `weights/model.bin`, `tokenizer/vocab.json`). The backend reconstructs the directory tree and calls `upload_folder` once, creating the folder structure directly in your HF repository.

**Edge cases handled**:
- Empty folder groups are flagged with an error and block upload.
- Duplicate folder names are flagged immediately when the second is entered.
- Files with no folder name go to the repository root.

---

### 2. Deploy a Public Repository

The **Deploy** tab now has a **Deploy a Public Repository** section alongside the existing "deploy selected model" flow.

**Steps**:
1. Sign in with your HF token.
2. Go to the **Deploy** tab.
3. Scroll to the **Deploy a Public Repository** section.
4. Enter a public HF repository identifier (e.g., `bert-base-uncased` or `meta-llama/Llama-2-7b`).
5. Click **Fetch Repository Info**. The platform validates the repo is public and displays its metadata (description, file count, total size).
6. Once the metadata is shown, click **CPU** or **GPU** to trigger the mock deployment.
7. A spinner appears (~2 seconds) and a `mock_success` result is displayed.

**Error cases**:
- If the repository does not exist or is private, an error message is displayed and no deployment is triggered.
- If the identifier format is invalid (`owner/repo-name` required), validation fires before the API call.

---

## API Reference

The updated API contract is at `specs/005-folder-upload-repo-deploy/contracts/api.yml`.

Key changes from v1.0.0:
- `POST /api/upload/start` — `filename` fields may now include a single folder prefix (`folder_name/file`).
- `GET /api/models/public?repo_id=...` — **new endpoint** for fetching public model metadata.
