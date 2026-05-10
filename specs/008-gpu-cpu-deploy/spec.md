# Feature Specification: GPU / CPU Hardware Selector for Public Model Deployment

**Feature Branch**: `008-gpu-cpu-deploy`  
**Created**: 2026-05-10  
**Status**: Draft  
**Input**: User description: "I want to enable users to pick GPU or CPU while deploying public models from huggingface. Users should be able to select either of them. Then, backend will use two different path for them. TGI-CPU is already done but has some legacy named files. Do not make major edits on CPU path. Create GPU path with vLLM. Use LitServe for GPU path. Deploy GPU models to https://lightning.ai/deploy. Be careful with user feedback on the app."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Select CPU and Deploy a Public Model on GKE (Priority: P1)

A logged-in user with valid GCP credentials navigates to the **Deploy a Public Repository** section. They enter a HuggingFace model ID, fetch its metadata, and are presented with a **CPU / GPU** hardware selector before initiating the deployment. They select **CPU** and click Deploy. The platform routes the deployment through the existing TGI-CPU inference path on GKE Autopilot and shows live progress messages while the deployment is being provisioned.

**Why this priority**: CPU deployment already works end-to-end and is the most risk-free path. Wiring the selector to the existing CPU path is the minimum viable change that delivers the hardware-selector feature with zero regression risk.

**Independent Test**: Can be fully tested by entering a valid public HF model ID → selecting CPU → clicking Deploy, and verifying that the system creates a deployment record with `hardware_type = cpu` and the orchestrator uses the TGI-CPU manifest generator. Delivers a working selector UI + CPU routing without needing the GPU path.

**Acceptance Scenarios**:

1. **Given** a logged-in user with valid GCP credentials and a valid public HF model ID entered, **When** the user selects CPU and clicks Deploy, **Then** the platform creates a deployment record tagged `cpu`, shows a spinner with live status text (e.g. "Deploying CPU inference server…"), and transitions through `queued → deploying → running` using the existing GKE Autopilot flow.
2. **Given** a user who has selected CPU, **When** the deployment enters the provisioning phase, **Then** the status message clearly states it is a CPU deployment (not GPU), so the user is never confused about what is running.
3. **Given** a user who submits a CPU deploy request, **When** the backend processes it, **Then** the TGI-CPU Kubernetes manifest is applied without any breaking changes to the existing CPU path.

---

### User Story 2 — Select GPU and Deploy a Public Model via Lightning AI (Priority: P2)

A logged-in user with a configured Lightning AI API key selects **GPU** when deploying a public HF model. The platform submits the model to [Lightning AI's managed deployment platform](https://lightning.ai/deploy) using a LitServe inference server backed by vLLM. Lightning AI handles GPU provisioning, autoscaling, and uptime entirely. The user sees GPU-specific status messages (e.g. "Submitting to Lightning AI…", "GPU deployment live") and receives the Lightning AI endpoint URL when the deployment is ready.

**Why this priority**: GPU support is the primary new capability this feature delivers, but it depends on the selector UI (P1) being in place first.

**Independent Test**: Can be fully tested by selecting GPU → clicking Deploy → verifying that the backend calls Lightning AI's deployment API with the correct LitServe server definition and that the deployment record is tagged `gpu` with a Lightning AI endpoint URL. A fake Lightning AI provider can stand in for contract tests.

**Acceptance Scenarios**:

1. **Given** a logged-in user with a valid Lightning AI API key, **When** they select GPU and click Deploy, **Then** the backend submits a LitServe + vLLM server definition to Lightning AI cloud, records `hardware_type = gpu` on the deployment row, and transitions the status through `queued → deploying → running`.
2. **Given** a GPU deployment being submitted to Lightning AI, **When** the status is polled, **Then** status messages shown in the UI are GPU-specific and Lightning AI-specific (e.g. "Submitting to Lightning AI…", "Waiting for GPU node to come online…", "GPU inference server live").
3. **Given** a GPU deployment that has reached `running`, **When** the user sends an inference request, **Then** the request is forwarded to the Lightning AI endpoint URL and a valid response is returned through the existing inference proxy.
4. **Given** a user without a configured Lightning AI API key, **When** they select GPU and attempt to deploy, **Then** the UI shows a clear error directing them to the **⚡ Lightning AI** tab to enter their API key before GPU deployment is possible.

---

### User Story 3 — Clear User Feedback During and After Hardware Selection (Priority: P3)

At every stage of the deployment flow — before selection, during provisioning, and after completion or failure — the UI gives the user accurate, hardware-aware feedback. CPU deployments reference GKE and CPU-specific terminology; GPU deployments reference Lightning AI and GPU-specific terminology. Errors on either path are surfaced with actionable language distinct from the other path.

**Why this priority**: Correct feedback is critical for user trust, but it is additive and does not block the core routing.

**Independent Test**: Can be fully tested by running a CPU deploy and a GPU deploy in sequence and asserting that the spinner text, success message, and deployment detail all reflect the correct hardware type and platform.

**Acceptance Scenarios**:

1. **Given** a user who has not yet selected a hardware type, **When** they view the Deploy section after fetching model info, **Then** the UI displays a clearly labelled CPU / GPU radio selector so the choice is unambiguous before the Deploy button is active.
2. **Given** a CPU deployment in any non-terminal state, **When** the user views its status, **Then** no GPU-related labels, icons, or references to Lightning AI are shown.
3. **Given** a GPU deployment that fails on the Lightning AI side (e.g. API key invalid, Lightning AI service error), **When** the user views the failure message, **Then** the message names Lightning AI as the affected service and provides a clear next step (check API key, retry, or contact support).

---

### Edge Cases

- What happens when the user changes the hardware selector after fetching model info but before clicking Deploy? The most recently selected hardware type is used; no stale-state risk.
- What if the selected model is too large for CPU (e.g. exceeds the CPU node's memory limit)? The deployment enters `failed` with a message specific to CPU resource limits.
- What if the Lightning AI API key is invalid or expired? The GPU deployment immediately transitions to `failed` with a message explaining that the API key is invalid and directing the user to update it.
- What if Lightning AI's platform is temporarily unavailable? The GPU deployment is marked `failed` with a transient-error message and a suggestion to retry.
- What if a GPU deployment stays in `deploying` for an extended period? The platform does not impose its own timeout; the deployment remains `deploying` until Lightning AI reports a terminal state (success or failure). The UI displays a live status message from Lightning AI so the user can see progress.
- What if neither CPU nor GPU is selected when the user clicks Deploy? The Deploy button is disabled until a hardware type is selected; submission without selection is not possible.
- What if a user has GCP credentials but no Lightning AI API key and selects GPU? The UI shows a pre-flight error directing the user to the **⚡ Lightning AI** tab to enter their API key before the deploy request is submitted.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Deploy a Public Repository UI MUST present a hardware selector (CPU or GPU) after model info is fetched, and the Deploy button MUST remain inactive until a hardware type is chosen.
- **FR-002**: The hardware selector MUST default to no selection; users MUST explicitly choose before deploying.
- **FR-003**: The `DeployRequest` payload sent to `POST /api/deployments` MUST include a `hardware_type` field with values `"cpu"` or `"gpu"`.
- **FR-004**: The backend MUST persist `hardware_type` on the deployment record so status polling and UI rendering can reflect the correct hardware and target platform.
- **FR-005**: When `hardware_type = cpu`, the orchestrator MUST use the existing TGI-CPU Kubernetes manifest generator without any breaking changes to its logic or file structure (legacy file names MUST NOT be renamed in this feature).
- **FR-006**: When `hardware_type = gpu`, the backend MUST submit a LitServe inference server definition (using vLLM as the backend) to Lightning AI's managed deployment platform via the Lightning AI Python SDK (`lightning` package), rather than provisioning a GKE cluster.
- **FR-007**: GPU deployments MUST NOT require GCP credentials; they MUST require a Lightning AI API key that is stored and retrieved via a dedicated credential entry in the platform.
- **FR-008**: Live status messages during provisioning MUST be hardware-and-platform-specific: CPU deploys reference GKE and CPU; GPU deploys reference Lightning AI and GPU.
- **FR-009**: The Deploy button MUST be disabled until the user has selected a hardware type AND model info has been fetched successfully.
- **FR-010**: The existing mock-deploy flow for personal models (features 004/005/006) MUST remain unchanged; this feature's hardware selector applies only to the public-repo real-deploy flow.
- **FR-011**: When a GPU deployment fails due to a Lightning AI API key problem, the status message MUST name Lightning AI and direct the user to check or update their API key.
- **FR-012**: The inference proxy endpoint (`POST /api/deployments/{id}/inference`) MUST work for both CPU (GKE) and GPU (Lightning AI) deployments; the proxy forwards to whichever endpoint URL is stored on the deployment record.
- **FR-013**: The platform MUST perform a pre-flight credential check before submitting a GPU deployment: if no Lightning AI API key is configured, the request MUST fail immediately with a `credentials_missing` error before any Lightning AI API call is made.
- **FR-014**: The Streamlit app MUST include a dedicated **⚡ Lightning AI** tab where users can enter, view (masked), and delete their Lightning AI API key — mirroring the UX of the existing **☁️ GCP Credentials** tab.
- **FR-015**: The platform MUST NOT impose a deployment timeout for GPU deployments on Lightning AI; the polling loop MUST continue until Lightning AI reports a terminal state (`running` or an error). The UI MUST display the current Lightning AI-reported status message during the wait so users are not left with a silent spinner.

### Key Entities

- **DeployRequest** (extended): HuggingFace model ID + `hardware_type` (cpu | gpu) + force flag.
- **DeploymentRow** (extended): Persists `hardware_type` alongside existing fields; the orchestrator uses it to select the correct deployment path (GKE for CPU, Lightning AI for GPU).
- **TGI-CPU Manifest** (existing, unchanged): Kubernetes manifest for HuggingFace TGI on CPU (`vllm_manifest.py` — legacy name retained).
- **LitServe Server Definition** (new): A LitServe server script (or equivalent programmatic representation) that wraps vLLM for the target HF model, submitted to Lightning AI's cloud deployment API.
- **Lightning AI Credential** (new): A per-user Lightning AI API key encrypted with Fernet and stored in `llmops.db` under a `lightning_ai` credential type, using the same `LLMOPS_ENCRYPTION_KEY` environment variable as GCP credentials.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can select a hardware type and initiate a public-model deployment in under 60 seconds from first page load (excluding cloud provisioning time on either platform).
- **SC-002**: 100% of CPU deployments continue to succeed without any regressions in the existing TGI-CPU path after this feature is shipped (verified by the existing contract and integration test suite).
- **SC-003**: GPU deployments that reach `running` state on Lightning AI successfully respond to inference requests forwarded through the existing proxy endpoint; status transitions are reflected in the UI within 30 seconds of Lightning AI reporting them.
- **SC-004**: Every deployment detail visible in the UI correctly reflects both the hardware type and target platform — CPU deployments show GKE context; GPU deployments show Lightning AI context.
- **SC-005**: Contract tests for the GPU Lightning AI path cover the happy path, API key missing, API key invalid, and Lightning AI service error scenarios using a fake Lightning AI provider that stubs the Lightning AI Python SDK — no real cloud calls required.
- **SC-006**: The Deploy button cannot be activated without a hardware-type selection; zero accidental deployments without an explicit hardware choice.
- **SC-007**: Pre-flight credential checks prevent GPU deployment attempts when no Lightning AI API key is configured, surfacing a clear error before any external API call is made.

---

## Clarifications

### Session 2026-05-10

- Q: How should the Lightning AI API key be stored at rest? → A: Encrypted with Fernet in `llmops.db`, mirroring GCP credential storage exactly (same `LLMOPS_ENCRYPTION_KEY` env var).
- Q: How should the platform track GPU deployment status after submission to Lightning AI? → A: Backend polls Lightning AI's status API on a timer (mirrors existing GCP 30 s status-refresh loop).
- Q: Which integration method should the backend use to communicate with Lightning AI? → A: Lightning AI Python SDK (`lightning` package).
- Q: Where in the Streamlit UI should users manage their Lightning AI API key? → A: New dedicated tab "⚡ Lightning AI", mirroring the existing "☁️ GCP Credentials" tab pattern.
- Q: If a GPU deployment never reaches `running`, when/how should the platform mark it `failed`? → A: No platform-side timeout — rely entirely on Lightning AI to report a terminal error state; the deployment stays `deploying` until Lightning AI resolves it.

---

## Assumptions

- The existing TGI-CPU manifest generator in `vllm_manifest.py` is **not renamed or refactored** in this feature; the file name's legacy mismatch is accepted tech debt.
- The Lightning AI Python SDK (`lightning` package) is used to submit LitServe server definitions and poll deployment status; the SDK returns a deployment ID and endpoint URL that are stored in the existing deployment record.
- The Lightning AI endpoint serves an OpenAI-compatible HTTP API (standard for vLLM), so the existing inference proxy forwards requests without modification.
- Each user's Lightning AI API key is encrypted with Fernet and stored in `llmops.db` under a `lightning_ai` credential type, reusing the existing `LLMOPS_ENCRYPTION_KEY` environment variable; it is stored separately from GCP credentials.
- GPU deployments bypass the GCP orchestrator (no GKE cluster, no GCP project); they use a separate Lightning AI orchestrator path that polls Lightning AI's status API on the same 30-second interval used by the GCP status-refresh loop.
- Lightning AI handles GPU node selection, autoscaling, and uptime; the platform does not need to manage GPU node pools or Kubernetes resource specs for the GPU path.
- The hardware selector applies exclusively to the **Deploy a Public Repository** flow. The personal-model mock-deploy flow is out of scope for this feature.
- Mobile/responsive layout of the hardware selector is out of scope for v1; standard Streamlit column layout is sufficient.
- Users are responsible for having a valid Lightning AI account with sufficient credits for GPU inference; the platform stores and forwards the API key but does not manage billing.
- The platform does not impose a deployment timeout for GPU deployments; Lightning AI is expected to eventually report a terminal state (running or failed) for every submission. No `lost`-equivalent recovery path is defined for GPU deployments in this feature.
