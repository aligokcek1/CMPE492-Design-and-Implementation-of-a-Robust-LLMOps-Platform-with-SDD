# Data Model: Robust Model Upload

## Entities

### `HuggingFaceAuth`
Represents the user's authenticated session with Hugging Face.
- `access_token` (string): Hugging Face fine-grained or write-access token. Must be kept secure and never exposed to the frontend permanently, or kept in memory only.
- `username` (string): The user's Hugging Face username retrieved after token validation.

### `LocalModelSession`
Represents a user's local directory selected for upload.
- `session_id` (uuid): Unique identifier for the upload session.
- `local_path` (string): The local absolute path to the directory (backend perspective) or a handle/metadata from the frontend (browser perspective via File API).
- `repository_name` (string): Target Hugging Face repository ID (e.g. `username/my-model`).
- `status` (enum): `pending`, `uploading`, `completed`, `failed`.
- `progress` (float): 0.0 to 1.0 representation of upload progress.

### `MockDeployment`
Represents a mock deployment request to GCP.
- `model_repository` (string): The Hugging Face model ID to "deploy".
- `resource_type` (enum): `CPU`, `GPU`.
- `deployment_status` (enum): `pending`, `mock_success`.

## Validation Rules
- `HuggingFaceAuth.access_token` MUST be validated against Hugging Face `/api/whoami-v2` endpoint before proceeding.
- `LocalModelSession.repository_name` MUST follow Hugging Face naming constraints (alphanumeric with hyphens/underscores).
- All files in the selected local directory are included (no mandatory file validation per spec).