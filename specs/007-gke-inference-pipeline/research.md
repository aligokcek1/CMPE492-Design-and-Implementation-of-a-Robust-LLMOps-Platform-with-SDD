# Phase 0 Research: GKE Inference Pipeline

**Feature**: 007-gke-inference-pipeline
**Date**: 2026-04-16
**Source tutorial**: <https://docs.cloud.google.com/ai-hypercomputer/docs/tutorials/gpu/qwen3-vllm-inference>

The Google tutorial demonstrates serving **Qwen3-235B** on an **A4 VM with 8× NVIDIA B200** — hardware reserved in advance and priced at the top of GCP's catalog. The spec explicitly says "use the cheapest instances." This research maps the tutorial's high-end reference stack down to the cheapest viable equivalent for small Qwen3-class models.

---

## Decision 1: GKE mode — Autopilot vs Standard

**Decision**: **GKE Autopilot**.

**Rationale**:
- Autopilot manages nodes, upgrades, security patches, and capacity automatically — aligning with the spec's "as user friendly as possible" goal. The pipeline only needs to submit pod specs.
- Autopilot does billing at the pod level (CPU/memory/GPU requests). For a single always-on inference pod the delta vs Standard is small.
- The Google tutorial uses Autopilot (`gcloud container clusters create-auto`).
- Autopilot removes per-node IAM, driver-install, and node-pool scaling code from our orchestrator.

**Alternatives considered**:
- **GKE Standard**: Slightly cheaper for a single always-on node, but requires managing node pools, GPU driver installation DaemonSets, auto-repair policies, and surprise node upgrades. Extra code + edge cases; rejected for simplicity.
- **Cloud Run GPU**: Can serve vLLM but has stricter constraints on startup time (container cold-start limit), no persistent storage for large weights caches, and is still preview-only in many regions. Rejected for robustness.

---

## Decision 2: Cheapest GPU for Qwen3-class text generation

**Decision**: **NVIDIA L4 (24 GB VRAM)**, 1 GPU per pod, in `us-central1`.

**Rationale**:
- L4 is GCP's cheapest modern inference GPU; list price ≈ $0.65/hr as of current pricing (~$470/mo 24/7).
- 24 GB VRAM comfortably fits Qwen3 models up to ~8B parameters at bf16; smaller variants (0.6B, 1.7B, 4B) run with headroom.
- Autopilot accelerator request: `cloud.google.com/gke-accelerator: nvidia-l4` + `nvidia.com/gpu: "1"` + `cloud.google.com/compute-class: "Accelerator"`.
- `us-central1` has wide L4 availability and is among the lowest-priced regions.

**Alternatives considered**:
- **NVIDIA T4 (16 GB)**: Cheapest at ~$0.35/hr, but 16 GB VRAM blocks 7–8B models at bf16, limiting the catalog of deployable public models. Rejected — too restrictive.
- **NVIDIA A100 / H100 / B200**: 10–50× more expensive than L4. Directly contradicts the "cheapest" constraint. Rejected.
- **CPU-only serving**: Technically possible for tiny models, but latency is unacceptable for a user-facing inference panel (minutes per token). Rejected.

---

## Decision 3: vLLM container image

**Decision**: `vllm/vllm-openai:latest` (pin to a specific digest in production manifests).

**Rationale**:
- Official vLLM image; ships with the OpenAI-compatible REST server (`/v1/chat/completions`, `/v1/completions`, `/health`, `/metrics`).
- Lets the in-UI inference panel speak the same protocol the endpoint exposes publicly — no translation layer on our side.
- The Google tutorial uses a Vertex fork of the image because they need specific B200 tuning; on L4 we don't need that fork.

**Alternatives considered**:
- **Text Generation Inference (TGI) from HuggingFace**: Comparable quality but a different REST schema. Would require us to maintain a protocol adapter in the inference-proxy. Rejected — extra complexity, no tangible upside.
- **Custom container**: Rejected — over-engineering (Principle III: direct library usage).

---

## Decision 4: GCP project provisioning and teardown

**Decision**: Use Python Google Cloud client libraries directly — `google-cloud-resource-manager`, `google-cloud-billing`, `google-cloud-container`. No Terraform.

**Rationale**:
- Each deployment corresponds to an **ephemeral** GCP project (spec: one project per deployment). There is no long-term infra state to version-control, which is Terraform's primary value proposition.
- Python clients integrate naturally with the FastAPI backend and the existing async pipeline style.
- Fewer moving pieces in the runtime: no `terraform` binary, no state file (local or remote), no lockfile contention.

**Provisioning sequence** (orchestrator):
1. `ResourceManagerClient.create_project(project_id)` with auto-generated id `llmops-<short-hex>-<shortname>`.
2. `CloudBillingClient.update_project_billing_info(project_id, billing_account)`.
3. `ServiceUsageClient.enable_service("container.googleapis.com")` (and `compute.googleapis.com`).
4. `ClusterManagerClient.create_cluster` (Autopilot, region `us-central1`).
5. Wait for cluster readiness (polled by the orchestrator; informs UI status).
6. Fetch cluster credentials, construct a `kubernetes.client.ApiClient` against the cluster's endpoint with the impersonated service-account token.
7. `kubectl apply` the generated vLLM `Deployment` + `Service` (type `LoadBalancer`) + `Secret` (HF token).
8. Poll `Deployment.status.availableReplicas >= 1` and `Service.status.loadBalancer.ingress[].ip` to derive the endpoint URL.

**Teardown**: `ResourceManagerClient.delete_project(project_id)` — cascades everything (cluster, LB, disks, etc.). Much simpler than per-resource cleanup.

**Alternatives considered**:
- **Terraform**: Adds a second toolchain, needs state management per ephemeral project, and its strength (drift detection on long-lived infra) is irrelevant here. Rejected.
- **`gcloud` CLI shell-outs**: Slower, awkward error handling (parsing stdout/stderr), harder to test. Rejected.

---

## Decision 5: Public endpoint shape

**Decision**: Kubernetes `Service type=LoadBalancer` on port 80, targeting pod port 8000. No Ingress, no custom domain.

**Rationale**:
- Simplest path to a usable public URL. GCP provisions an L4 Network LB automatically (~$18/mo).
- Endpoint URL format: `http://<lb-ip>/v1/chat/completions` — a raw IPv4, hard to guess by brute force at internet scale.
- The spec accepts "endpoint URL acts as implicit secret" — a random IP satisfies that.
- Leaves the vLLM OpenAI-compatible API unchanged, so external callers and the in-UI panel use identical request bodies.

**Alternatives considered**:
- **Ingress + managed cert**: Adds domain management and certificate provisioning. Out of scope; spec explicitly defers auth to a future iteration.
- **NodePort + firewall rule on the node IP**: Cheaper but the node IP can change under Autopilot scaling; would break the stored endpoint URL. Rejected.

---

## Decision 6: Credential storage at rest

**Decision**: SQLite file + SQLAlchemy ORM. Service-account JSON encrypted with `cryptography.fernet.Fernet` using a key read from `LLMOPS_ENCRYPTION_KEY` env var.

**Rationale**:
- Spec mandates persistence through restart for both credentials and deployment records.
- Fernet is symmetric AES-128-CBC + HMAC — strong enough for our threat model (server compromise ≈ game over regardless; we defend against casual disk access only).
- The API never returns the raw JSON. The stored plaintext is only decrypted in memory at the moment a GCP client is instantiated.
- SQLite + SQLAlchemy are trivial to operate and test; the DB file lives at `backend/data/llmops.db` and is `.gitignore`-d.

**Alternatives considered**:
- **Google Secret Manager**: Would chicken-and-egg the problem (we'd need *another* set of credentials to reach Secret Manager before the user has provided any). Rejected.
- **Plaintext on disk**: Violates Principle II (Security First). Rejected.
- **Environment variables only** (no persistence): Violates the persistence clarification. Rejected.

---

## Decision 7: In-UI inference timeout

**Decision**: Client-side timeout of 120 s on the backend httpx client that proxies `/v1/chat/completions`. No server-side timeout override on vLLM.

**Rationale**:
- SC-008 specifies exactly 120 s for the in-platform panel.
- httpx's `Timeout(connect=10, read=120, write=10, pool=5)` matches the SC.
- vLLM itself has no per-request timeout by default — we don't interfere.

**Alternatives considered**:
- Per-request streaming (SSE) would mask timeout behavior. Useful future enhancement; out of scope for v1.

---

## Decision 8: Testing strategy for the GCP boundary

**Decision**: Define a single `GCPProvider` protocol in `backend/src/services/gcp_provider.py`. Provide two implementations:

- `RealGCPProvider` (uses google-cloud-* directly; injected by default at runtime)
- `FakeGCPProvider` (pure-Python in-memory; simulates async project + cluster creation with short sleeps; tracks deletion)

Dependency-inject into the orchestrator via FastAPI's standard `Depends`. Tests always override the dependency to the fake. **No test — under any condition — imports or calls `RealGCPProvider`.**

**Rationale**:
- Running real GCP bring-up in CI would cost $$ and take 15–30 min per test case — not feasible.
- The GCP project / Billing / GKE cluster-create REST APIs expose **no dry-run flag**, so there is no zero-side-effect way to exercise them from a test. Any attempt would create real billable resources.
- The fake lives at the **boundary**, not between production code and the cloud libs — `RealGCPProvider` still uses google-cloud-* directly (Principle III).

**Dry-run where it exists — Kubernetes manifests only**:
- The `kubernetes` Python client supports `dry_run=["All"]` (server-side dry-run) on create/patch/apply. This lets us validate generated vLLM `Deployment` + `Service` manifests — including admission webhook checks — against a real API server without persisting anything.
- Implemented as an opt-in suite `backend/tests/dryrun/test_vllm_manifest_dryrun.py`, gated on the `LLMOPS_K8S_DRYRUN_KUBECONFIG` environment variable (path to a scratch kubeconfig). Skipped whenever the variable is unset.
- This suite never calls GCP APIs. A developer can run it locally against kind/minikube/a scratch cluster.

**Alternatives considered**:
- **"Live GCP smoke test" gated by `LLMOPS_GCP_LIVE=1`** (as initially sketched): rejected — it would create real billable resources. Even opt-in, it risks accidental invocation in CI and normalizes the idea that tests can touch cloud.
- **gcloud emulator / GKE emulator**: No usable emulator exists for project + GKE provisioning.
- **Record-and-replay (VCR)**: Would couple tests to a single replay of a flaky, expensive flow. Rejected.
