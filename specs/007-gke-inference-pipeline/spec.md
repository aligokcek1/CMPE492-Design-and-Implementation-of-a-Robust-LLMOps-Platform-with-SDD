# Feature Specification: GKE Inference Pipeline for Public HuggingFace Models

**Feature Branch**: `007-gke-inference-pipeline`
**Created**: 2026-04-16
**Status**: Draft
**Input**: User description: "Replace the mock and build the public model inference pipeline from Huggingface repositories to GKE on GCP. No need to include personal repositories for now, public models are adequate for now. Inference of personal models could be still mockup. A new project on GCP should be created for each deployment. Users should be able to see their deployments and delete the project they created. Required IDs and keys should be possibly input by users from the application dashboard. For simplicity, for now, do not make the deployment configurable from the dashboard. Use the cheapest instances. The process should be as user friendly as possible."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure GCP Credentials (Priority: P1)

A platform user wants to connect their GCP account so the platform can create and manage cloud resources on their behalf. They navigate to the dashboard settings, enter their GCP service account key and billing account ID, and the platform validates and saves these credentials for future deployments.

**Why this priority**: Without valid GCP credentials saved, no real deployment can proceed. This is the foundational prerequisite for all other stories.

**Independent Test**: Can be fully tested by entering credentials, submitting the form, and verifying the platform confirms or rejects the credentials — delivers the ability to onboard users onto GCP-backed workflows.

**Acceptance Scenarios**:

1. **Given** a logged-in user with no GCP credentials saved, **When** they open the credentials section of the dashboard and submit a valid service account key and billing account ID, **Then** the platform validates the credentials, saves them, and shows a success confirmation.
2. **Given** a logged-in user, **When** they submit invalid or malformed credentials, **Then** the platform shows a clear error message explaining what is wrong without saving the credentials.
3. **Given** a logged-in user who previously saved credentials, **When** they update and re-submit new credentials, **Then** the platform replaces the old credentials and confirms the update.

---

### User Story 2 - Deploy a Public HuggingFace Model to GCP (Priority: P2)

A platform user selects a public HuggingFace model they have previously identified and triggers a deployment. The platform automatically creates a new dedicated GCP project, provisions the cheapest appropriate cloud resources, and deploys the model so it can serve inference requests. The user is kept informed of progress throughout the process.

**Why this priority**: This is the core value proposition of the feature — replacing the mock with a real, working inference deployment.

**Independent Test**: Can be fully tested by selecting a public HF model and clicking deploy; delivers a live inference endpoint the user can interact with.

**Acceptance Scenarios**:

1. **Given** a logged-in user with valid GCP credentials saved, **When** they select a public HuggingFace model from the platform and initiate deployment, **Then** the platform creates a new GCP project dedicated to that deployment, deploys the model using the cheapest available cloud resources, and shows real-time status updates until deployment is complete.
2. **Given** a deployment is in progress, **When** the user views the deployments section, **Then** they see the deployment listed with a "deploying" status and progress feedback.
3. **Given** a deployment completes successfully, **When** the user views the deployments section, **Then** they see the deployment listed with a "running" status and an inference endpoint address.
4. **Given** a deployment fails (e.g., insufficient permissions, quota exceeded), **When** the user views the deployments section, **Then** they see the deployment listed with a "failed" status and a human-readable explanation of the failure. Any partially-created GCP resources are cleaned up automatically.
5. **Given** a user with no GCP credentials saved, **When** they attempt to deploy a public model, **Then** the platform guides them to configure credentials first before proceeding.

---

### User Story 3 - View Active Deployments (Priority: P3)

A platform user wants an overview of all models they have deployed. They can see each deployment's name, the underlying HuggingFace model, current status, and the endpoint URL they can use for inference.

**Why this priority**: Without visibility into existing deployments, users cannot manage costs or know whether their models are available.

**Independent Test**: Can be fully tested independently by listing existing deployments and confirming the displayed information is accurate.

**Acceptance Scenarios**:

1. **Given** a logged-in user with one or more active deployments, **When** they navigate to the deployments section, **Then** they see a list of all their deployments, each showing: model name, HuggingFace source, current status, and inference endpoint URL (for running deployments).
2. **Given** a logged-in user with no deployments, **When** they navigate to the deployments section, **Then** they see a friendly empty-state message guiding them to create their first deployment.
3. **Given** a logged-in user viewing their deployments, **When** a deployment's status changes (e.g., from "deploying" to "running"), **Then** the updated status is reflected without the user having to leave and return to the page.

---

### User Story 4 - Delete a Deployment (Priority: P4)

A platform user wants to decommission a model deployment they no longer need. They select a deployment from their list and confirm deletion. The platform tears down all associated GCP cloud resources and removes the deployment from the user's list, ensuring no further costs are incurred.

**Why this priority**: Cost management is essential; users must be able to remove deployments they no longer need without leaving orphaned cloud resources.

**Independent Test**: Can be fully tested by creating a deployment, deleting it, and confirming the deployment disappears from the list and GCP resources are removed.

**Acceptance Scenarios**:

1. **Given** a logged-in user with a running or failed deployment, **When** they select "Delete" and confirm the action, **Then** the platform deletes the corresponding GCP project and all its resources, and removes the deployment from the user's list.
2. **Given** a deletion is in progress, **When** the user views the deployments section, **Then** they see the deployment listed with a "deleting" status until the process completes.
3. **Given** deletion is requested on a deployment currently being created, **When** the user confirms deletion, **Then** the platform cancels the in-progress deployment and cleans up any partial resources, then removes the entry from the list.
4. **Given** a GCP-side deletion failure (e.g., transient error), **When** the user views the deployments section, **Then** they see a clear error message and a retry option.

---

### User Story 5 - Run Inference on a Deployed Model (Priority: P5)

A platform user wants to test or use a model they have successfully deployed. From the deployment detail view, they can send an input query and receive a model response directly within the platform UI.

**Why this priority**: Without being able to invoke the model, deployment has no immediate user-facing value; however, the endpoint is also accessible externally, making this UI feature supplementary.

**Independent Test**: Can be fully tested by submitting a test prompt through the deployment detail view and confirming a response is returned.

**Acceptance Scenarios**:

1. **Given** a logged-in user viewing a running deployment, **When** they submit an input via the inference panel in the UI, **Then** the platform sends the input to the deployed model and displays the response within the UI.
2. **Given** a model that takes longer than expected to respond, **When** the user waits up to 120 seconds, **Then** the UI shows a loading indicator throughout. If no response is received within 120 seconds, the UI displays a timeout error with a retry option.
3. **Given** an inference request that fails, **When** the error is returned, **Then** the UI displays a friendly error message with guidance to retry.

---

### Edge Cases

- What happens when GCP quota limits are reached during deployment creation? → Treated as a deployment failure: the platform surfaces a human-readable error (mentioning quota as the cause), cleans up any partial resources, and transitions the deployment to "failed" status (FR-009).
- How does the system handle a GCP project creation that partially succeeds before a failure? → The platform automatically tears down all partially-created GCP resources and transitions the deployment to "failed" status with a human-readable explanation (FR-009).
- What happens when the user's GCP credentials expire or are revoked after a deployment is already running? → Running deployments continue (they operate independently of platform credentials); new deployments and deletion actions are blocked with a persistent dashboard warning until the user updates their credentials.
- How does the system handle a user attempting to deploy the same public model twice simultaneously? → Allowed; the platform shows a confirmation warning ("You already have a running deployment of this model — continue?") before creating the second deployment.
- What happens when a deployment's GCP project is deleted manually outside the platform? → The platform marks the deployment as "lost" on the next status check and displays a clear explanation; the user must explicitly dismiss the record to remove it from their list.
- What happens when a user already has 3 running deployments and tries to initiate a fourth? → The platform blocks the action with a message prompting the user to delete an existing deployment first (FR-013).
- How does the system behave when the HuggingFace model repository becomes unavailable after deployment starts? → If unavailable during initial model download (deploy phase): treated as a deployment failure with cleanup (FR-009). If unavailable after the deployment is already running: no impact — the model is already loaded and serving inference requests independently of HuggingFace.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to enter, save, and update their GCP service account credentials (service account key) and GCP billing account ID via the application dashboard. Credentials MUST be stored in a persistent, encrypted store and survive backend restarts.
- **FR-002**: The platform MUST validate GCP credentials at the time of submission and notify users of any validation errors with clear, actionable messages.
- **FR-003**: When a user deploys a public HuggingFace model, the platform MUST automatically create a new, dedicated GCP project for that deployment. The deployment record (including the GCP project ID) MUST be persisted so it survives backend restarts.
- **FR-004**: The platform MUST deploy the selected public HuggingFace model to GKE using pre-configured, cheapest-available instance settings with no user configuration required.
- **FR-005**: The platform MUST provide real-time status feedback during deployment (e.g., "Creating project", "Provisioning cluster", "Deploying model", "Ready").
- **FR-006**: The platform MUST display a list of all deployments belonging to the authenticated user, including: model name, HuggingFace source, status, and inference endpoint URL for running deployments.
- **FR-007**: Users MUST be able to delete any of their deployments, which MUST trigger full teardown of the corresponding GCP project and all associated resources.
- **FR-008**: The platform MUST expose an inference endpoint for each successfully deployed public model. The endpoint URL requires no authentication to call (publicly accessible), but MUST only be displayed to the owning user within the platform UI. The endpoint URL MUST NOT be shared with or visible to other users.
- **FR-009**: The platform MUST surface human-readable error messages when deployment or deletion fails, and MUST automatically clean up any partially-created GCP resources on deployment failure.
- **FR-010**: Deployments of personal (user-uploaded) models MUST continue to return mocked inference responses; no real GCP deployment is created for personal models.
- **FR-011**: The platform MUST prevent deployment initiation if the user has not yet configured valid GCP credentials, and MUST guide the user to complete credential setup first.
- **FR-013**: The platform MUST enforce a maximum of 3 concurrent running deployments per user. Attempting to deploy while at the limit MUST display a clear message prompting the user to delete an existing deployment first.
- **FR-016**: If a user initiates a deployment for a public HuggingFace model they already have a running deployment for, the platform MUST display a confirmation warning before proceeding. The user may confirm and create the second deployment (up to the 3-deployment cap), or cancel.
- **FR-012**: Users MUST NOT be able to view or interact with deployments belonging to other users.
- **FR-014**: When a deployment's underlying GCP project is found to no longer exist during a status check, the platform MUST transition the deployment to a "lost" status and display a clear explanation to the user. The user MUST be able to explicitly dismiss (permanently remove) a "lost" deployment record.
- **FR-015**: When the platform detects that a user's stored GCP credentials are invalid or revoked, it MUST display a persistent warning on the dashboard. New deployment creation and deletion of existing deployments MUST be blocked until the user updates their credentials. Already-running deployments MUST continue to operate and serve inference requests unaffected.

### Key Entities

- **GCP Credentials**: A user-specific record holding the GCP service account key (JSON) and billing account ID required for cloud resource management. Belongs to one user. MUST be stored in a persistent, encrypted store that survives backend restarts.
- **Deployment**: Represents a single deployed model instance. Attributes include: owning user, source HuggingFace model identifier, associated GCP project ID, current lifecycle status (queued / deploying / running / failed / deleting / deleted / lost), inference endpoint URL, and creation timestamp. MUST be persisted so the platform can manage (and delete) corresponding GCP projects across restarts. A "lost" status indicates the underlying GCP project was removed outside the platform.
- **Public Model**: A model sourced from a public HuggingFace repository, identified by its repository ID. Used as the artifact to be served.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user who has configured credentials can complete the full deploy flow (select model → initiate deployment) in under 3 minutes of active interaction time.
- **SC-002**: Deployment status updates are reflected in the UI within 30 seconds of the underlying cloud status changing, without requiring a manual page refresh.
- **SC-003**: Deleting a deployment removes 100% of associated GCP resources within 10 minutes of user confirmation.
- **SC-004**: A deployed public model accepts and returns an inference response within 60 seconds of the deployment reaching "running" status.
- **SC-008**: The in-platform inference panel displays a timeout error after exactly 120 seconds with no response, and always offers a retry option.
- **SC-005**: GCP credential validation rejects invalid credentials and provides an actionable error message 100% of the time before any cloud resources are created.
- **SC-006**: 90% of deployment attempts for supported public HuggingFace model types succeed without requiring user intervention (assuming valid credentials and sufficient GCP quota).
- **SC-007**: Users with no prior cloud infrastructure knowledge can successfully complete a first deployment by following in-platform guidance alone, without consulting external documentation.

## Clarifications

### Session 2026-04-16 (continued)

- Q: Should GCP credentials and deployment records persist across backend restarts? → A: Yes — introduce a lightweight persistent store (e.g. encrypted file or embedded DB) for both credentials and deployment records.
- Q: Should the inference endpoint require authentication to call? → A: Endpoint is publicly callable (no auth on the endpoint itself); the URL is only revealed to the owning user through the platform UI.
- Q: Should there be a maximum number of concurrent running deployments per user? → A: Yes — cap at 3 concurrent running deployments per user.
- Q: What should happen when a GCP project backing a deployment is deleted outside the platform? → A: Mark the deployment as "lost" on the next status check with a clear explanation; the user explicitly dismisses/removes the record.
- Q: What should happen when GCP credentials become invalid while deployments are running? → A: Running deployments continue unaffected; new deployments and deletion actions are blocked until credentials are updated; a persistent warning is shown to the user.
- Q: Can a user deploy the same public HuggingFace model more than once simultaneously? → A: Allowed, but the platform MUST show a confirmation warning ("You already have a running deployment of this model — continue?") before proceeding.
- Q: What is the maximum wait time for the in-platform inference panel before showing a timeout error? → A: 120 seconds (2 minutes).

## Assumptions

- Users have an active GCP account with billing enabled and a service account that has sufficient IAM permissions to create and delete GCP projects and manage GKE resources.
- Users have a GCP billing account ID they can locate from their GCP console.
- Only text generation / NLP models (e.g. Qwen3, GPT-style, T5, BERT-style) are in scope for real GKE deployment in this iteration. Image, audio, and multimodal model types are out of scope; attempting to deploy such models may produce an unsupported-model error.
- Deployment configuration (instance type, region, replicas) is fixed by the platform and not exposed to users in this version; the platform always selects the cheapest appropriate option.
- GCP project names are auto-generated by the platform (users do not name projects).
- Each deployment corresponds to exactly one GCP project; one user may have multiple deployments (multiple projects).
- The platform runs with network access to both the HuggingFace API and the GCP APIs.
- Existing session-based authentication (feature 006) is the sole access gate; no additional authorization layer is introduced in this feature.
- Personal model inference (user-uploaded models) continues to use the existing mock deployment path and is unaffected by this feature.
- Cost management (budget alerts, spending caps) is out of scope for this iteration; users are responsible for monitoring their own GCP spend.
- Inference endpoint authentication is out of scope for this iteration. The endpoint URL acts as an implicit secret — it is never displayed to users other than the owner, and a future feature may add explicit endpoint auth.
