# Tasks: Robust Model Upload Flow to Hugging Face

**Branch**: `004-robust-model-upload`  
**Input**: Feature specification from `/specs/004-robust-model-upload/spec.md`

## Implementation Strategy

We will deliver this feature incrementally using a Streamlit frontend + FastAPI backend architecture. 
- **MVP (User Story 1)**: Will establish the basic infrastructure and authenticate the user with Hugging Face.
- **Incremental additions**: Subsequent user stories will add the core upload flow (US2), model selection (US3), and finally the mock GCP deployment (US4).

## Phase 1: Setup
*Goal: Initialize the project structure and baseline dependencies.*

- [X] T001 Initialize FastAPI backend structure with `uvicorn` and `huggingface_hub` in `backend/src/main.py`
- [X] T002 [P] Initialize Streamlit frontend structure in `frontend/src/app.py`
- [X] T003 Set up backend `pytest` and `pytest-asyncio` configurations in `backend/pytest.ini`
- [X] T004 [P] Set up frontend `pytest` configurations for Streamlit testing in `frontend/pytest.ini`
- [X] T005 Create CORS middleware for FastAPI to allow frontend communication in `backend/src/main.py`

## Phase 2: Foundational
*Goal: Establish core API routing, error handling, and models required by all downstream tasks.*

- [X] T006 Implement base HTTP error handler in `backend/src/api/errors.py`
- [X] T007 Create `HuggingFaceAuth` Pydantic model for backend token validation in `backend/src/models/auth.py`
- [X] T008 Create API client wrapper for Streamlit to communicate with FastAPI in `frontend/src/services/api_client.py`

## Phase 3: User Story 1 - Sign in with Hugging Face (Priority: P1)
*Goal: As a user, I want to authenticate using my Hugging Face account so that I can securely access and upload models to my repositories.*
*Independent Test: Can be fully tested by implementing a login flow using Hugging Face tokens, allowing the system to retrieve the user's profile and list their repositories.*

- [X] T009 [US1] Write contract test for `/api/auth/verify` endpoint in `backend/tests/contract/test_auth_api.py`
- [X] T010 [US1] Implement Hugging Face token verification service using `huggingface_hub` in `backend/src/services/huggingface.py`
- [X] T011 [US1] Implement POST `/api/auth/verify` endpoint in `backend/src/api/auth.py`
- [X] T012 [US1] Build Login UI component allowing token input and displaying validation errors using TDD (write component tests first using `streamlit.testing`) in `frontend/src/components/auth.py`
- [X] T013 [US1] Integrate Login UI with backend `/api/auth/verify` via `api_client` and store session state in `frontend/src/app.py`

## Phase 4: User Story 2 - Upload and Stage Local Models (Priority: P1)
*Goal: As a user, I want to securely and reliably upload a local LLM model to the Hugging Face Hub so that it can be staged for stable deployment.*
*Independent Test: Can be tested by selecting a local model directory and verifying that it is successfully uploaded to a designated Hugging Face repository.*

- [X] T014 [US2] Write contract test for `/api/upload/start` endpoint in `backend/tests/contract/test_upload_api.py`
- [X] T015 [US2] Implement `LocalModelSession` Pydantic models for upload payload in `backend/src/models/upload.py`
- [X] T016 [US2] Implement resumable directory upload logic utilizing `huggingface_hub.upload_folder` in `backend/src/services/huggingface.py`
- [X] T017 [US2] Implement POST `/api/upload/start` endpoint to handle file streams/paths in `backend/src/api/upload.py`
- [X] T018 [US2] Create Streamlit upload UI component (handling directory/multiple files) and progress indicators using TDD in `frontend/src/components/upload.py`
- [X] T019 [US2] Integrate upload component with backend upload API, passing auth token and tracking progress in `frontend/src/app.py`

## Phase 5: User Story 3 - Select Existing Hugging Face Models (Priority: P2)
*Goal: As a user, I want to select an existing model directly from a Hugging Face repository so that I can deploy models without needing to upload them first.*
*Independent Test: Can be tested by searching or browsing the Hugging Face Hub via the UI and selecting a valid model repository for deployment.*

- [X] T020 [US3] Write contract test for `/api/models` endpoint in `backend/tests/contract/test_models_api.py`
- [X] T021 [US3] Add `list_models` capability to the Hugging Face service in `backend/src/services/huggingface.py`
- [X] T022 [US3] Implement GET `/api/models` endpoint to retrieve user's existing repositories in `backend/src/api/models.py`
- [X] T023 [US3] Build Model Selection UI (dropdown or list) fetching data from backend using TDD in `frontend/src/components/upload.py`
- [X] T024 [US3] Integrate Model Selector into the main workflow, allowing users to bypass upload in `frontend/src/app.py`

## Phase 6: User Story 4 - Mock GCP Deployment Selection (Priority: P3)
*Goal: As a user, I want to select GCP deployment options (CPU or GPU) and see a simulated deployment process so that I can validate the end-to-end UI workflow.*
*Independent Test: Can be tested by selecting deployment hardware options and observing a simulated success response.*

- [X] T025 [US4] Write contract test for `/api/deployment/mock` endpoint in `backend/tests/contract/test_deployment_api.py`
- [X] T026 [US4] Implement `MockDeployment` request/response models in `backend/src/models/deployment.py`
- [X] T027 [US4] Create mock GCP deployment service that simulates a delay and returns success in `backend/src/services/mock_gcp.py`
- [X] T028 [US4] Implement POST `/api/deployment/mock` endpoint in `backend/src/api/deployment.py`
- [X] T029 [US4] Build Deployment Configuration UI (CPU/GPU toggle buttons) using TDD in `frontend/src/components/deploy.py`
- [X] T030 [US4] Integrate Deployment Configuration UI with mock backend endpoint and display simulated success state in `frontend/src/app.py`

## Phase 7: Polish & Cross-Cutting
*Goal: Ensure end-to-end reliability, style consistency, and handle edge cases outlined in the spec.*

- [X] T031 Handle edge case: display clear error if Hugging Face token lacks write permissions during upload in `frontend/src/components/upload.py`
- [X] T032 Handle edge case: Ensure `huggingface_hub.upload_folder` is configured to handle large files gracefully without exceeding available memory (chunked uploads) in `backend/src/services/huggingface.py`
- [X] T033 Handle edge case: ensure proper HTTP 409 conflict handling if target repository already exists under a different user in `backend/src/api/upload.py`
- [X] T034 Add global error handling and `st.toast` / `st.error` notifications for seamless user experience in `frontend/src/app.py`
- [X] T035 Perform end-to-end integration test of the full workflow (Login -> Upload -> Deploy) using Pytest/Streamlit Testing in `frontend/tests/integration/test_workflow.py`

---
## Dependencies
- Phase 1 must be completed before Phase 2.
- Phase 2 is a strict prerequisite for all User Story phases (Phases 3-6).
- Phase 3 (Authentication) is required before Phase 4 (Upload) and Phase 5 (Select Model) as all interact with Hugging Face.
- Phase 6 (Mock Deployment) requires a model to be selected, thus depending on Phase 4 or Phase 5.
- Phase 7 (Polish) should be executed last.

## Parallel Execution
- **Setup**: Backend and Frontend initialization (T001, T002) can happen concurrently.
- **US1**: Backend Auth API (T011) and Frontend Auth UI (T012) can be built simultaneously.
- **US2**: The directory upload logic (T016) and the Streamlit upload UI (T018) are independent tasks.
- **US4**: Backend Mock API (T028) and Frontend Config UI (T029) can be developed in parallel.
