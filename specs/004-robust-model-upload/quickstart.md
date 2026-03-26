# Quickstart: Robust Model Upload Setup

This guide explains how to set up the development environment for the Robust Model Upload feature.

## Prerequisites
- Python 3.11+
- A Hugging Face account and an Access Token (with `write` permissions).

## Backend Setup (FastAPI)
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install fastapi uvicorn huggingface_hub pytest pytest-asyncio
   ```
4. Run the development server:
   ```bash
   uvicorn src.main:app --reload
   ```

## Frontend Setup (Streamlit)
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Create and activate a virtual environment (or use the same one):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install streamlit requests pytest
   ```
4. Run the development server:
   ```bash
   streamlit run src/app.py
   ```

## Running Tests
- **Backend**: Run `pytest` inside the `backend` directory.
- **Frontend**: Run `pytest` inside the `frontend` directory.