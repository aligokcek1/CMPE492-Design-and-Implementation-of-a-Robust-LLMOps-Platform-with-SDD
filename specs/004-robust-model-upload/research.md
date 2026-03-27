# Research & Technical Decisions: Robust Model Upload

## Language/Version
- **Decision**: Python 3.11 for both Backend and Frontend.
- **Rationale**: Python is the industry standard for AI/ML tooling and integrates natively with Hugging Face libraries. Using Python for the frontend simplifies the stack and allows rapid iteration.
- **Alternatives considered**: TypeScript/React frontend (rejected due to user explicitly requesting a basic Streamlit frontend for functionality over form).

## Primary Dependencies
- **Decision**: `FastAPI` (Backend), `huggingface_hub` (Backend), `Streamlit` (Frontend).
- **Rationale**: `FastAPI` offers high performance and automatic OpenAPI docs. `huggingface_hub` Python library has built-in robust upload methods (e.g., `upload_folder`) with resume capabilities, perfectly matching our 10GB robust upload constraint. `Streamlit` allows for extremely fast UI development purely in Python.
- **Alternatives considered**: Direct REST API calls to Hugging Face (rejected because `huggingface_hub` handles chunking, concurrency, and retries natively). React/Vite for frontend (rejected per explicit user request).

## Testing
- **Decision**: `pytest` and `pytest-asyncio` for Backend; `pytest` with `streamlit.testing` for Frontend.
- **Rationale**: Strict TDD mandates fast, reliable test runners. `pytest` is the Python standard.
- **Alternatives considered**: `unittest` (too verbose).