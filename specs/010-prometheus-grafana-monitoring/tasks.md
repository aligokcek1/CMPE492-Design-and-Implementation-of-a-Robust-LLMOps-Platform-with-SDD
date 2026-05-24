# Tasks: Deployment Metrics Monitoring with Prometheus and Grafana

**Input**: Design documents from `specs/010-prometheus-grafana-monitoring/`
**Branch**: `010-prometheus-grafana-monitoring`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**TDD**: Tests are included (constitution principle IV mandates Red-Green-Refactor). Write each test task before its corresponding implementation task. Verify the test fails (red) before implementing (green).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: User story label (US1, US2, US3, US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Monitoring stack assets and new backend dependency.

- [x] T001 Add `prometheus-client` to backend dependencies in `backend/pyproject.toml` (or equivalent deps file used by the project)
- [x] T002 [P] Create `docker-compose.monitoring.yml` at repo root with Prometheus (`9090`) and Grafana (`3000`) services; configure Prometheus with `--storage.tsdb.retention.time=30d` and `--web.enable-lifecycle` per `specs/010-prometheus-grafana-monitoring/quickstart.md` and Assumptions (30-day active retention)
- [x] T003 [P] Create base Prometheus config at `backend/monitoring/prometheus.yml` with `scrape_config_files: ['scrape.d/*.yml']`, global `scrape_interval: 15s` (SC-002 freshness target), and backend self-scrape job for `GET /metrics`
- [x] T004 [P] Create `backend/monitoring/scrape.d/.gitkeep` directory for per-deployment scrape job fragments
- [x] T005 [P] Create Grafana dashboard template at `backend/monitoring/grafana/dashboards/deployment-metrics.json` with panels for TTFT, throughput, CPU/memory, and GPU (N/A-safe)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB schema, metric instrumentation, provisioner protocols, orchestration hooks, and query layer that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T006 Add `DeploymentMonitoringRow` SQLAlchemy model to `backend/src/db/models.py` per `specs/010-prometheus-grafana-monitoring/data-model.md`
- [x] T007 Write additive migration for `deployment_monitoring` table in `backend/src/db/migrations.py` (gate on table absence via inspector)
- [x] T008 [P] Create Pydantic models (`MetricPoint`, `HardwareSeries`, `MetricsSummary`, `MetricsSeriesBundle`, `DeploymentMetricsResponse`, `GrafanaLinkResponse`) in `backend/src/models/metrics.py`
- [x] T009 [P] Implement `metrics_recorder.py` with `llmops_ttft_seconds`, `llmops_tokens_total`, and `llmops_inference_requests_total` in `backend/src/services/metrics_recorder.py`
- [x] T010 Instrument `inference_proxy.forward()` to record TTFT, token counts, and request outcomes via `metrics_recorder`; extend `forward()` signature to accept `deployment_id` and `user_id` labels; update `backend/src/api/deployment.py` inference handler to pass `deployment_id`, `session.username`, and `row.hardware_type` into `metrics_recorder` on every inference request
- [x] T011 [P] Implement `PrometheusProvisioner` protocol + file-based scrape job writer/reloader in `backend/src/services/prometheus_provisioner.py`
- [x] T012 [P] Implement `FakePrometheusProvisioner` (records provision/decommission calls, no filesystem writes) in `backend/src/services/prometheus_fake_provisioner.py`
- [x] T013 [P] Implement `GrafanaProvisioner` protocol + Grafana HTTP API client (datasource + dashboard import) in `backend/src/services/grafana_provisioner.py`
- [x] T014 [P] Implement `FakeGrafanaProvisioner` (returns deterministic UIDs) in `backend/src/services/grafana_fake_provisioner.py`
- [x] T015 [P] Implement `GrafanaSignedUrlService` (HMAC mint + validate using `LLMOPS_GRAFANA_SIGNING_SECRET`) in `backend/src/services/grafana_signed_url.py`
- [x] T016 Implement `MetricsStore` CRUD (`create_active`, `get_for_deployment`, `mark_decommissioning`, `list_due_for_decommission`, `delete`) in `backend/src/services/metrics_store.py`
- [x] T017 Implement `MonitoringOrchestrator` (`provision_for_running_deployment`, `schedule_decommission`, `run_decommission_cycle`, `reconcile_on_startup`) in `backend/src/services/monitoring_orchestrator.py`
- [x] T018 Hook `MonitoringOrchestrator` into `deployment_orchestrator` when status transitions to `running` (provision) and `deleted` (schedule decommission) in `backend/src/services/deployment_orchestrator.py`
- [x] T019 Mount backend Prometheus exposition at `GET /metrics` via `prometheus_client.make_asgi_app()` and register empty `metrics` router in `backend/src/main.py`
- [x] T020 [P] Add `FakePrometheusProvisioner`, `FakeGrafanaProvisioner`, and `FakeMetricsQueryClient` fixtures to `backend/tests/contract/conftest.py`
- [x] T021 [P] Add `get_prometheus_provisioner`, `get_grafana_provisioner`, and test-reset overrides to `backend/src/api/dependencies.py`
- [x] T022 Implement `MetricsQueryService.fetch_deployment_metrics()` with server-side PromQL label injection (`deployment_id`, `user_id`) in `backend/src/services/metrics_query.py`

**Checkpoint**: Foundation ready — proxy metrics emit, monitoring rows can be provisioned/decommissioned, query service stub exists.

---

## Phase 3: User Story 1 — View Performance Metrics for a Running Deployment (Priority: P1) 🎯 MVP

**Goal**: Running deployments show **TTFT and throughput summary** in a native Streamlit metrics panel; non-running/deleted deployments show no metrics entry point. (Hardware utilization charts are US3; trend charts are US2.)

**Independent Test**: Deploy a model → wait for `running` → send inference → open metrics panel → verify TTFT and throughput summaries appear (or explicit empty state before first request).

### Tests for User Story 1 (write FIRST — verify red before implementing)

- [x] T023 [P] [US1] Write contract tests in `backend/tests/contract/test_metrics_api.py`: (a) `GET /api/deployments/{id}/metrics` on running deployment with active `deployment_monitoring` row returns 200 with TTFT + throughput summary fields; (b) no inference traffic returns `empty: true`; (c) non-running/deleted deployment returns 404; (d) foreign user's deployment returns 403; (e) Prometheus unreachable returns explicit error (503 or 200 with `error` field); (f) running deployment without provisioned monitoring row returns 503 with clear message (FR-004a)
- [x] T024 [P] [US1] Add frontend AppTest cases to `frontend/tests/integration/test_workflow.py`: metrics expander visible on `running` deployment; metrics expander absent on `deleted`/`deploying` deployment

### Implementation for User Story 1

- [x] T025 [US1] Implement `GET /api/deployments/{deployment_id}/metrics` (auth + ownership + running-only guard + active `deployment_monitoring` row required per FR-004a) in `backend/src/api/metrics.py`
- [x] T026 [US1] Implement summary PromQL queries (avg TTFT, throughput with tokens/s vs requests/s fallback) in `backend/src/services/metrics_query.py`
- [x] T027 [P] [US1] Add `get_deployment_metrics(token, deployment_id, range)` to `frontend/src/services/api_client.py`
- [x] T028 [US1] Create `render_deployment_metrics_panel()` with summary `st.metric` widgets, empty state, and error state in `frontend/src/components/deployment_metrics.py`
- [x] T029 [US1] Embed metrics panel for `status == "running"` deployments only in `frontend/src/components/deployments_list.py`
- [x] T030 [US1] Backend checkpoint — run `cd backend && pytest tests/contract/test_metrics_api.py` and verify all US1 tests pass (green)

**Checkpoint**: MVP metrics panel live for running deployments — TTFT + throughput summaries with empty/error/provisioning states.

---

## Phase 4: User Story 2 — Track TTFT and Throughput Trends Over Time (Priority: P2)

**Goal**: Users select time ranges (1h / 24h / 7d) and see TTFT + throughput trend charts with p95 and failed-request exclusion indicator.

**Independent Test**: Generate inference traffic over a known window → select each range → verify chart series cover the window with labeled axes/units.

### Tests for User Story 2 (write FIRST — verify red before implementing)

- [x] T031 [P] [US2] Extend `backend/tests/contract/test_metrics_api.py`: (a) `range=1h|24h|7d` returns time-series arrays; (b) summary includes `ttft_p95_seconds`; (c) `failed_requests_excluded: true` present when failed requests occurred
- [x] T032 [P] [US2] Add frontend AppTest to `frontend/tests/integration/test_workflow.py`: time range selector changes displayed chart data (mock API returns distinct series per range)

### Implementation for User Story 2

- [x] T033 [US2] Extend `MetricsQueryService` with `/api/v1/query_range` PromQL for TTFT and throughput trends in `backend/src/services/metrics_query.py`
- [x] T034 [US2] Add `range` query param validation and p95 TTFT aggregation to `GET /api/deployments/{id}/metrics` in `backend/src/api/metrics.py`
- [x] T035 [US2] Add time range `st.selectbox` and `st.line_chart` trend charts for TTFT and throughput in `frontend/src/components/deployment_metrics.py`
- [x] T036 [US2] Display failed-request exclusion note in metrics panel when applicable in `frontend/src/components/deployment_metrics.py`

**Checkpoint**: Trend analysis available in-platform for all three time ranges.

---

## Phase 5: User Story 3 — Compare Hardware Utilization by Deployment Type (Priority: P3)

**Goal**: CPU deployments show CPU/memory charts labeled GKE/TGI; GPU deployments show GPU/memory when available or explicit N/A labels — never fabricated GPU values.

**Independent Test**: Run one CPU and one GPU deployment → open each metrics panel → verify correct resource types, platform labels, and GPU N/A when hardware series absent.

### Tests for User Story 3 (write FIRST — verify red before implementing)

- [x] T037 [P] [US3] Extend `backend/tests/contract/test_metrics_api.py`: (a) CPU deployment returns `cpu_utilization.available=true` and `gpu_utilization.available=false`; (b) GPU deployment with no GPU series returns `gpu_utilization.available=false` with reason `not_available_for_this_deployment_type`; (c) TTFT/throughput still populated for GPU N/A case
- [x] T038 [P] [US3] Add frontend AppTest to `frontend/tests/integration/test_workflow.py`: CPU panel shows "GKE / TGI" label; GPU panel shows "Lightning AI" label; GPU N/A renders explicit message not blank chart

### Implementation for User Story 3

- [x] T039 [US3] Add hardware PromQL queries (`process_cpu_seconds_total`, `process_resident_memory_bytes`, GPU series probe) with `available`/`reason` flags in `backend/src/services/metrics_query.py`
- [x] T040 [US3] Include `platform_label` (`GKE / TGI` vs `Lightning AI / GPU`) and hardware bundle in API response in `backend/src/api/metrics.py`
- [x] T041 [US3] Render hardware utilization charts with CPU/GPU-specific labels and N/A messaging in `frontend/src/components/deployment_metrics.py`
- [x] T042 [US3] Ensure per-deployment isolation — metrics query always filters by `deployment_id` + `user_id` with no cross-deployment aggregation in `backend/src/services/metrics_query.py`

**Checkpoint**: Hardware panels correctly differentiated by deployment type with honest GPU fallback.

---

## Phase 6: User Story 4 — Access Grafana Dashboards from the Platform (Priority: P4)

**Goal**: Running deployments expose **Open in Grafana** via HMAC-signed redirect; expired/tampered/deleted tokens rejected; no separate Grafana login.

**Independent Test**: Click **Open in Grafana** on running deployment → land on scoped dashboard; expired token returns 403; deleted deployment returns 404 on link mint.

### Tests for User Story 4 (write FIRST — verify red before implementing)

- [x] T043 [P] [US4] Write contract tests in `backend/tests/contract/test_metrics_api.py`: (a) `GET /api/deployments/{id}/metrics/grafana` returns `redirect_url` + `expires_at` for running deployment; (b) deleted/non-running returns 404; (c) foreign user returns 403; (d) `GET /api/metrics/grafana/redirect?token=` valid token 302s to Grafana URL; (e) expired/tampered token returns 403
- [x] T044 [P] [US4] Add frontend AppTest to `frontend/tests/integration/test_workflow.py`: **Open in Grafana** button visible on running deployment only; clicking calls API and opens returned URL

### Implementation for User Story 4

- [x] T045 [US4] Implement `GET /api/deployments/{deployment_id}/metrics/grafana` (mint signed redirect URL) in `backend/src/api/metrics.py`
- [x] T046 [US4] Implement `GET /api/metrics/grafana/redirect` (validate HMAC token → 302 to `{GRAFANA_URL}/d/{dashboard_uid}`) in `backend/src/api/metrics.py`
- [x] T047 [US4] Wire `GrafanaProvisioner` to import per-deployment dashboard from `backend/monitoring/grafana/dashboards/deployment-metrics.json` during provision in `backend/src/services/monitoring_orchestrator.py`
- [x] T048 [P] [US4] Add `get_grafana_link(token, deployment_id)` to `frontend/src/services/api_client.py`
- [x] T049 [US4] Add **Open in Grafana** button (opens signed redirect in new tab) to `frontend/src/components/deployment_metrics.py`; hide when deployment not `running`

**Checkpoint**: Hybrid UX complete — in-platform charts plus signed Grafana deep links.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Lifecycle hardening, background jobs, and end-to-end validation.

- [x] T050 Start 60 s background decommission loop calling `MonitoringOrchestrator.run_decommission_cycle()` in `backend/src/main.py` lifespan (respect `LLMOPS_METRICS_DISABLED=1`)
- [x] T051 Call `MonitoringOrchestrator.reconcile_on_startup()` on backend startup to restore scrape jobs for existing `running` deployments in `backend/src/main.py`
- [x] T052 [P] Add inference-records-metrics contract test to `backend/tests/contract/test_deployment_api.py`: POST inference on running deployment increments observable metric sample (via fake query client or `/metrics` exposition parse)
- [x] T053 [P] Update `.cursor/rules/specify-rules.mdc` project structure section with new monitoring modules and API routes from feature 010
- [x] T054 Run full validation per `specs/010-prometheus-grafana-monitoring/quickstart.md`: `docker compose -f docker-compose.monitoring.yml up -d`, deploy model, verify metrics panel + Grafana link E2E

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **BLOCKS all user stories**
- **User Stories (Phases 3–6)**: All depend on Phase 2 completion
  - Recommended sequential order: US1 → US2 → US3 → US4 (each builds on metrics API + panel)
  - US3 and US4 can partially parallelize after US1 (different query vs Grafana paths)
- **Polish (Phase 7)**: Depends on US1–US4 completion

### User Story Dependencies

| Story | Depends on | Delivers independently |
|-------|------------|------------------------|
| **US1 (P1)** | Foundational | TTFT + throughput summary panel (MVP); hardware in US3 |
| **US2 (P2)** | US1 metrics API + panel shell | Time-range trend charts |
| **US3 (P3)** | US1 metrics API + panel shell | Hardware charts + GPU N/A |
| **US4 (P4)** | Foundational provisioners + US1 panel | Grafana signed deep links |

### Within Each User Story

- Tests MUST be written and fail (red) before implementation (green)
- Backend query/service changes before frontend panel changes
- Story checkpoint test run before moving to next priority

### Parallel Opportunities

**Phase 1** — T002, T003, T004, T005 in parallel after T001

**Phase 2** — After T006–T007 (DB first):
- T008–T015 all parallel (models, recorder, provisioners, signed URL)
- T020–T021 parallel with T016–T19 once protocols exist

**Phase 3 US1** — T023 + T024 parallel; T027 parallel with T025–T026

**Phase 4 US2** — T031 + T032 parallel

**Phase 5 US3** — T037 + T038 parallel

**Phase 6 US4** — T043 + T044 parallel; T048 parallel with T045–T047

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
# T023: backend/tests/contract/test_metrics_api.py
# T024: frontend/tests/integration/test_workflow.py

# Implementation (partial parallel):
# T027: frontend/src/services/api_client.py
# T025–T026: backend/src/api/metrics.py + metrics_query.py (sequential)
# T028–T029: frontend panel + deployments_list.py
```

---

## Parallel Example: Foundational Phase

```bash
# After T006–T007 (DB):
# T008 metrics Pydantic models
# T009 metrics_recorder.py
# T011–T014 prometheus + grafana provisioners (real + fake)
# T015 grafana_signed_url.py
# T020–T021 test fixtures + dependencies
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL**)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Metrics panel shows TTFT + throughput summaries for a running deployment
5. Demo MVP before trend charts (US2), hardware charts (US3), or Grafana links (US4)

### Incremental Delivery

1. Setup + Foundational → monitoring infrastructure ready
2. US1 → summary metrics panel (MVP)
3. US2 → trend charts + time ranges
4. US3 → hardware utilization + GPU N/A honesty
5. US4 → Grafana signed deep links
6. Polish → decommission loop + E2E quickstart validation

### Parallel Team Strategy

With multiple developers after Foundational:

- **Developer A**: US1 + US2 (metrics API + charts)
- **Developer B**: US3 (hardware queries + panel labels)
- **Developer C**: US4 (Grafana provisioning + signed redirect)

---

## Notes

- Set `LLMOPS_METRICS_DISABLED=1` in test conftest to skip real Prometheus/Grafana provisioning
- Never expose raw PromQL or signing secrets to the frontend (FR-009, constitution II)
- GPU hardware MUST NOT be inferred — return N/A with reason string (FR-003a)
- Metrics UI and Grafana links MUST disappear immediately on delete (FR-014a)
- Post-delete retention (7 days) is operator-only — no user-facing history

---

## Task Summary

| Phase | Tasks | Story |
|-------|-------|-------|
| Phase 1 Setup | T001–T005 (5) | — |
| Phase 2 Foundational | T006–T022 (17) | — |
| Phase 3 US1 | T023–T030 (8) | P1 MVP |
| Phase 4 US2 | T031–T036 (6) | P2 |
| Phase 5 US3 | T037–T042 (6) | P3 |
| Phase 6 US4 | T043–T049 (7) | P4 |
| Phase 7 Polish | T050–T054 (5) | — |
| **Total** | **54 tasks** | |

**MVP scope**: Phases 1–3 (T001–T030) = 30 tasks

**Parallel opportunities**: 22 tasks marked `[P]`
