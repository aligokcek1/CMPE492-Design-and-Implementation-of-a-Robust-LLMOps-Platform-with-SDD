# Feature Specification: Folder Upload and Public Repository Deployment

**Feature Branch**: `005-folder-upload-repo-deploy`  
**Created**: 2026-04-07  
**Status**: Draft  
**Input**: User description: "I want folder upload feature, users should be able to upload multiple folders. Also, users should be able to select a public repository to deploy."

## Clarifications

### Session 2026-04-07

- Q: Does "deploy" mean importing/registering into the platform, actively serving as an inference endpoint, or both? → A: "Deploy" means cloud deployment (mocked for now — the UI triggers a deployment flow but the actual cloud provisioning is simulated). "Upload" means pushing model folder contents to the user's Hugging Face repository.
- Q: When uploading multiple folders, do they all go to one HF repository or each to a separate one? → A: All selected folders are uploaded into a single user-specified HF repository; each folder becomes a subdirectory within that repository.
- Q: Does public repository selection use live search/autocomplete or direct text input? → A: Direct text input only — the user types the full public repository identifier (e.g., `owner/repo-name`); no search or autocomplete is required.
- Q: When two queued folders share the same name, should the upload be blocked until resolved, proceed by skipping, or let the user choose per-conflict? → A: Block — the upload cannot be started while any folder name conflict exists in the queue; the user must remove or resolve duplicates before proceeding.
- Q: How does the mocked deployment progress — staged status transitions with delay, instant resolution, or configurable? → A: The existing mock implementation (`mock_gcp.py`) applies a single ~2-second async delay then resolves directly to `mock_success` with no staged status transitions; this behaviour is preserved as-is.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload Multiple Folders (Priority: P1)

A platform user has a local model or dataset organized as one or more folders (e.g., model weights, tokenizer files, configs). They want to select multiple folders from their file system and upload them all into a single target Hugging Face repository in one session — each folder becoming a subdirectory within that repository — without having to trigger separate upload flows for each folder.

**Why this priority**: Folder-based upload is the primary new capability requested and is foundational for users who work with multi-component artifacts. Without it, users cannot use the repository deployment feature effectively either.

**Independent Test**: Can be fully tested by selecting multiple local folders through the upload interface and verifying that all folder contents appear correctly on the platform after the upload completes, delivering immediate value to users managing multi-folder model artifacts.

**Acceptance Scenarios**:

1. **Given** a user is on the upload page, **When** they select two or more folders from their file system, **Then** all selected folders and their contents are queued for upload and displayed in a pre-upload summary list.
2. **Given** a user has queued multiple folders, **When** the upload is initiated, **Then** all folders and their contents are uploaded and the user receives a success confirmation for each folder.
3. **Given** a user is uploading multiple folders and one folder's upload fails, **When** the error occurs, **Then** the remaining folders continue uploading and the failed folder is clearly identified with an actionable error message.
4. **Given** a user has a folder group with no files selected, **When** they attempt to initiate the upload, **Then** the system shows a warning on the empty group and disables the upload button until at least one file is added to each group.
5. **Given** a user has queued folders, **When** they want to remove one before uploading, **Then** they can deselect individual folders from the queue without affecting the others.

---

### User Story 2 - Select a Public Repository for Cloud Deployment (Priority: P2)

A platform user wants to select a publicly available Hugging Face repository and trigger a cloud deployment for it — without needing to upload any local files. They enter or search for a public repository identifier, review its metadata, and initiate a cloud deployment. The actual cloud provisioning is mocked in this version (the UI completes the deployment flow and shows a success state, but no real infrastructure is provisioned).

**Why this priority**: This unlocks a direct path from a public model to a "deployed" state, which is valuable for demonstrating the end-to-end LLMOps workflow. Cloud mocking keeps scope controlled while the real deployment backend is built separately.

**Independent Test**: Can be fully tested by entering a valid public Hugging Face repository identifier, confirming the metadata preview, triggering the mocked deployment, and verifying that the platform shows a completed deployment status — delivering a demonstrable end-to-end flow independently of the folder upload story.

**Acceptance Scenarios**:

1. **Given** a user is on the deployment page, **When** they enter a valid public Hugging Face repository identifier, **Then** the platform fetches repository metadata (name, size, file list) and displays a confirmation preview before deploying.
2. **Given** a user has confirmed the repository details, **When** they initiate deployment, **Then** the system simulates a cloud deployment and shows the user a success status upon completion of the mocked flow.
3. **Given** a user enters a repository identifier that does not exist or is private, **When** they attempt to fetch metadata, **Then** the system displays a clear error message indicating the repository could not be found or accessed.
4. **Given** a deployment request has been sent, **When** the user views the deployment area, **Then** they see a loading indicator while the mock processes (~2 seconds) followed by a clear success or failure result.
5. **Given** a deployment completes successfully, **When** the result is displayed, **Then** the user sees the `mock_success` status and a descriptive message confirming which repository and resource type were deployed.

---

### User Story 3 - Track Upload and Deployment Progress (Priority: P3)

A user uploading multiple large folders or deploying a large public repository wants real-time feedback on progress so they understand the system is working and can estimate completion time.

**Why this priority**: Progress visibility improves user confidence and reduces abandonment, but it is an enhancement to the core P1/P2 flows rather than a gating capability.

**Independent Test**: Can be fully tested by initiating a multi-folder upload or repository deployment and verifying that a progress indicator (per-folder and overall) updates in real time throughout the operation.

**Acceptance Scenarios**:

1. **Given** a multi-folder upload is in progress, **When** the user views the upload page, **Then** they see an overall progress indicator while the upload is active; once complete, they see a per-folder result summary (success or failure with error message for each folder).
2. **Given** a repository deployment is in progress, **When** the user views the deployment section, **Then** they see a loading/spinner indicator while the mock processes and the final outcome (success or failure) is displayed automatically upon completion.

---

### Edge Cases

- What happens when a folder contains nested sub-folders? The system should recursively include all sub-folder contents and preserve the directory structure.
- What happens when the total size of selected folders exceeds the platform's upload limit? The system should notify the user before starting the upload and prevent oversized uploads.
- What happens when two selected folders have the same name? The system detects the conflict immediately when the second folder is added to the queue, highlights both conflicting entries with an error, and prevents the upload from starting until the user removes one of the duplicates.
- What happens when a public repository is unavailable or rate-limited at the time of deployment? The system should retry automatically and surface a clear error if the issue persists.
- What happens if the user loses internet connection mid-upload? The system should detect the disconnect, pause the upload, and offer a resume option when connectivity is restored.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to select multiple folders simultaneously from their local file system and specify a single target Hugging Face repository ID for the entire batch.
- **FR-002**: System MUST display a pre-upload summary listing all selected folders, their sizes, and file counts before the upload begins.
- **FR-003**: Users MUST be able to add or remove individual folders from the upload queue before initiating the upload.
- **FR-004**: System MUST upload all queued folders into the single target Hugging Face repository, with each folder stored as a subdirectory preserving its internal directory structure.
- **FR-005**: System MUST display a per-folder success or failure result after the batch upload completes, along with an aggregate summary indicating how many folders succeeded and how many failed. An overall progress indicator MUST be shown while the upload is in progress.
- **FR-006**: System MUST continue uploading remaining folders if one folder's upload fails, and clearly report which folder(s) failed with actionable error messages.
- **FR-007**: System MUST detect folder groups with no files selected, display a specific warning on the affected group, and disable the upload button until all groups contain at least one file.
- **FR-007b**: System MUST detect folder name conflicts within the queue immediately upon adding a folder, highlight all conflicting entries, and block the upload from starting until all conflicts are resolved by the user removing the duplicate(s).
- **FR-008**: System MUST enforce a maximum total upload size limit and notify the user when the selected folders exceed it.
- **FR-009**: Users MUST be able to type a full public Hugging Face repository identifier (in `owner/repo-name` format) into a text input field to initiate deployment; no search or autocomplete is provided.
- **FR-010**: System MUST fetch and display repository metadata (name, description, file list, total size) for user confirmation before deployment begins.
- **FR-011**: System MUST prevent deployment of private or non-existent repositories and display an appropriate error message.
- **FR-012**: System MUST simulate (mock) the cloud deployment by issuing a single request that applies a short artificial delay (~2 seconds) and resolves directly to a success or failure outcome; no intermediate status polling is required.
- **FR-013**: System MUST display a spinner/loading state while the mocked deployment request is in flight and automatically show the final result (success or failure message) upon completion.
- **FR-014**: System MUST show the deployment result (status and message) persistently in the UI after completion so the user can review it without having to repeat the action.

### Key Entities

- **Upload Session**: Represents a single batch upload initiated by a user; contains a target HF repository ID, one or more folder entries, overall status, and per-folder progress.
- **Folder Entry**: A single folder selected for upload within an Upload Session; tracks folder name, size, file count, internal directory structure, upload status, and the subdirectory path it will occupy within the target repository.
- **Repository Deployment**: Represents a request to deploy a public repository; contains the repository identifier, metadata snapshot, deployment status, and timestamps.
- **Deployment Status**: The lifecycle state of a Repository Deployment. For the mocked implementation: `pending` (initiated, awaiting response) and `mock_success` (completed successfully). Real deployment statuses are a future extension.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can select, queue, and initiate upload of multiple folders in under 60 seconds from arriving at the upload page.
- **SC-002**: 95% of multi-folder upload sessions where no network interruption occurs complete successfully without user intervention.
- **SC-003**: A public repository deployment is initiated and confirmed by the user in under 2 minutes from entering the repository identifier.
- **SC-004**: Users see a progress indicator while a multi-folder upload or mock deployment is in progress, and receive a per-folder result summary immediately upon completion — without needing to refresh the page.
- **SC-005**: 90% of users successfully complete a multi-folder upload or repository deployment on their first attempt without seeking help.
- **SC-006**: Failed individual folder uploads do not abort the overall upload session; the remaining folders complete successfully in 100% of such cases.

## Assumptions

- Users are authenticated before accessing upload and deployment features; no new authentication mechanism is introduced by this feature.
- The platform already has an existing single-file upload pipeline; this feature extends it to support folders and batch operations.
- Public repositories refer to publicly accessible model/dataset repositories (e.g., on Hugging Face Hub); private repositories are explicitly out of scope.
- Folder upload is scoped to desktop/web browser interactions; mobile-specific folder picking behavior is out of scope for this version.
- The maximum upload size limit is an existing platform constraint; this feature surfaces it clearly in the UI rather than defining a new limit.
- Nested sub-folder structures are supported and directory hierarchy is preserved in the uploaded artifacts.
- Cloud deployment is mocked in this version: the deployment flow (status transitions, UI feedback) is real, but no actual cloud infrastructure is provisioned. Real cloud provisioning is a future feature.
- "Upload" refers exclusively to pushing local folder contents to the user's Hugging Face repository. "Deploy" refers exclusively to triggering a (mocked) cloud deployment for a selected public Hugging Face repository.
- The frontend is synchronous (Streamlit blocking model); per-folder progress cannot be streamed in real time during an active upload. Progress feedback is therefore provided as an overall spinner during the upload and a per-folder result summary upon completion.
- Automatic retry on HF rate-limiting and upload-pause/resume on internet disconnect are out of scope for this version and are deferred to a future feature.
