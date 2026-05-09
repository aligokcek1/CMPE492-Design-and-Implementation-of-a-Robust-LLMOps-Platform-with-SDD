# Phase 1 Data Model: GKE Inference Pipeline

**Feature**: 007-gke-inference-pipeline
**Storage**: SQLite via SQLAlchemy ORM. Database file: `backend/data/llmops.db` (git-ignored).

---

## Table: `gcp_credentials`

One row per platform user. Holds the user's GCP service-account key (encrypted) and billing account ID.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK autoincrement | |
| `user_id` | TEXT | NOT NULL, UNIQUE | Platform session user identifier (from feature 006 session registry). One credential record per user. |
| `service_account_json_encrypted` | BLOB | NOT NULL | Fernet-encrypted SA JSON. Plaintext never stored. |
| `billing_account_id` | TEXT | NOT NULL | GCP billing account, e.g. `billingAccounts/0X0X0X-XXXXXX-XXXXXX`. Stored plaintext (not a secret). |
| `service_account_email` | TEXT | NOT NULL | Parsed from the SA JSON for display in the UI (`sa-name@project.iam.gserviceaccount.com`). |
| `gcp_project_id_of_sa` | TEXT | NOT NULL | The parent project of the SA (from the JSON); displayed for confirmation. |
| `last_validated_at` | TIMESTAMP | NOT NULL | Time of last successful validation against GCP. |
| `validation_status` | TEXT | NOT NULL, CHECK IN (`valid`, `invalid`) | Updated on any orchestrator failure caused by an auth/permission error (supports FR-015). |
| `validation_error_message` | TEXT | NULL | Human-readable reason when `validation_status = 'invalid'`. |
| `created_at` | TIMESTAMP | NOT NULL, default now | |
| `updated_at` | TIMESTAMP | NOT NULL, auto-updated | |

**Validation rules** (enforced in service layer before persist):

- SA JSON must parse as JSON and contain `type="service_account"`, `client_email`, `private_key`, `project_id`.
- Billing account ID must match `^billingAccounts/[A-Z0-9-]{20}$`.
- Before save, the platform does a live check: lists projects accessible by the SA, and reads the billing account metadata — both must succeed. If either fails, the row is NOT saved and the user sees a clear error.

---

## Table: `deployments`

Zero-or-many per user. Each row maps 1:1 to a GCP project the platform provisioned.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | TEXT | PK | UUID v4 string. |
| `user_id` | TEXT | NOT NULL, INDEX | Owner (platform session user). |
| `hf_model_id` | TEXT | NOT NULL | e.g. `Qwen/Qwen3-1.7B`. |
| `hf_model_display_name` | TEXT | NOT NULL | Human-friendly label for the list view. |
| `gcp_project_id` | TEXT | NOT NULL, UNIQUE | Auto-generated: `llmops-<8-hex>-<slug>`. |
| `gke_cluster_name` | TEXT | NOT NULL | Always `llmops-cluster` within the per-deployment project. |
| `gke_region` | TEXT | NOT NULL | `us-central1` for v1. |
| `status` | TEXT | NOT NULL, CHECK IN (see below) | See state-machine section. |
| `status_message` | TEXT | NULL | Latest human-readable progress/error note. |
| `endpoint_url` | TEXT | NULL | Populated once `Service` LB IP is assigned. Format: `http://<ip>:80`. Combined with `/v1/chat/completions` by clients. |
| `created_at` | TIMESTAMP | NOT NULL, default now | |
| `updated_at` | TIMESTAMP | NOT NULL, auto-updated | Also used to detect stale in-progress rows on backend restart recovery. |
| `deleted_at` | TIMESTAMP | NULL | Set when status = `deleted`. Row retained briefly for UI, then eligible for cleanup. |

### Status state machine

```
       +------------+
       |  queued    |<-- initial (user clicked Deploy, order accepted)
       +-----+------+
             |
             v
       +------------+
       | deploying  |<-- orchestrator is creating project → cluster → vLLM
       +-----+------+
             |
         +---+---+---------------+
         v       v               v
    +--------+ +------+    +----------+
    |running | |failed|    | deleting |<-- (delete requested mid-creation)
    +--+-----+ +------+    +----+-----+
       |           ^             |
       |           |             v
       |      (optional)   +----------+
       |                   | deleted  |
       v                   +----------+
  +------+                       ^
  |lost  |----- user dismiss --->|
  +------+
```

Valid transitions:

| From | To | Trigger |
|---|---|---|
| `queued` | `deploying` | Orchestrator picks up the job |
| `queued` | `failed` | Preflight check fails (e.g. 3-cap hit in race) |
| `deploying` | `running` | Deployment becomes Available AND LB IP assigned |
| `deploying` | `failed` | Any provisioning error (quota, auth, image pull, etc.) |
| `deploying` | `deleting` | User initiates delete before it finishes |
| `running` | `deleting` | User clicks Delete |
| `running` | `lost` | Status-refresh job discovers the GCP project no longer exists |
| `failed` | `deleting` | User clicks Delete on a failed record (retry cleanup) |
| `deleting` | `deleted` | Project teardown confirmed by GCP |
| `deleting` | `failed` | Teardown error (user sees retry option) |
| `lost` | `deleted` | User dismisses the lost record (hard delete of DB row) |

### Entity-level rules

- A deployment **belongs to** exactly one `gcp_credentials` row (implicitly, via `user_id`). If the user deletes their credentials while deployments exist, the delete is **blocked** until all deployments are in `deleted`/`lost-dismissed` state.
- Before inserting a new `deployments` row with status `queued`, the service MUST check the user does not already have ≥3 deployments with status in (`queued`, `deploying`, `running`). If so, reject with `409 Conflict`.
- Before inserting a new `deployments` row, if any existing deployment of the **same user** with **same `hf_model_id`** is in (`queued`, `deploying`, `running`), the API returns `409 Conflict` with a `require_confirmation: true` hint. The client may retry with `force=true` to bypass (FR-016).

---

## Derived views

### `Deployment` response model (API)

Projected from `deployments` for the REST API:

```json
{
  "id": "uuid",
  "hf_model_id": "Qwen/Qwen3-1.7B",
  "hf_model_display_name": "Qwen3 1.7B",
  "status": "running",
  "status_message": "vLLM server ready",
  "endpoint_url": "http://34.12.34.56:80",
  "created_at": "...",
  "updated_at": "..."
}
```

`gcp_project_id`, `gke_cluster_name`, `gke_region` are deliberately omitted from default list responses (internal plumbing, not user-facing). They are included in the detail endpoint to support the user-facing "view in GCP Console" deep link.

### `GCPCredentials` response model (API)

Never exposes the SA JSON. Only status metadata:

```json
{
  "configured": true,
  "service_account_email": "sa@proj.iam.gserviceaccount.com",
  "gcp_project_id_of_sa": "proj-id",
  "billing_account_id": "billingAccounts/XXXXXX-YYYYYY-ZZZZZZ",
  "validation_status": "valid",
  "last_validated_at": "..."
}
```
