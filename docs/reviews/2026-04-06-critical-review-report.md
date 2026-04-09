# 6-Agent Critical Review Report

> **Date**: 2026-04-06
> **Scope**: Phase A~D 전체 코드베이스
> **Method**: Playwright E2E 테스트 실행 후, 6개 서브에이전트 병렬 비판 리뷰

## E2E Test Results

```
37 passed, 12 skipped, 0 failed (47s)
```

| Service | Tests | Result |
|---------|-------|--------|
| Grafana | 6 | All passed |
| MLflow | 4 | All passed |
| MinIO | 4 | All passed |
| Prefect | 3 | All passed |
| Prometheus | 4 | All passed |
| Label Studio | 3 | Skipped (DB not initialized) |
| Workflow Integration | 25 | 20 passed, 5 skipped |

**Skipped reasons**: Label Studio DB 미생성(7), 모델 미로드(5)

---

## Review Summary

| Perspective | Critical | Major | Minor | Total |
|-------------|----------|-------|-------|-------|
| 1. Native Feature Utilization | 2 | 5 | 0 | **7** |
| 2. Service Integration Completeness | 4 | 6 | 1 | **11** |
| 3. Advanced Feature Usage | 4 | 9 | 2 | **15** |
| 4. UX Improvements | 3 | 6 | 3 | **12** |
| 5. Security & Stability | 4 | 8 | 0 | **12** |
| 6. Unimplemented Features | 5 | 6 | 0 | **11** |
| **Total** | **22** | **40** | **6** | **68** |

---

## Critical Findings (Immediate Action Required)

### C1. Image Bytes Not Stored for Pseudo-Labels — Data Flywheel Cannot Close

**Perspectives**: Unimplemented, Integration
**Files**: `src/core/serving/api/routes.py:106-118`, `src/core/active_learning/accumulator/models.py:20`

`AccumulatedSample.image_ref` is documented as "placeholder for Phase A". During inference, only metadata is stored — actual image bytes are never uploaded to S3. The data integration task (`continuous_training_tasks.py:418`) skips records with empty `image_ref`. The dual-path data flywheel — the project's core differentiator — cannot function end-to-end.

### C2. `/admin/trigger-retraining` Has No Authentication

**Perspectives**: Security
**Files**: `src/core/serving/api/admin.py:16-58`, `src/core/serving/nginx/nginx.conf:25-37`

Nginx restricts `/model/reload` to private IPs, but `/admin/trigger-retraining` has no equivalent restriction. The endpoint accepts arbitrary `parameters: dict[str, Any]` forwarded directly to `run_deployment()`. Anyone who can reach port 8000 can trigger training with arbitrary parameters.

### C3. Label Studio Webhook Never Registered on Label Studio Side

**Perspectives**: Integration
**Files**: `src/core/active_learning/labeling/webhook.py`

FastAPI exposes `POST /webhooks/label-studio`, but no code registers this URL with Label Studio via its `POST /api/webhooks/` API. On a fresh deployment, Label Studio annotations produce no events. The labeling → retrain path is silently broken.

### C4. Webhook Endpoint Accepts Forged Events (No Signature Verification)

**Perspectives**: Security
**Files**: `src/core/active_learning/labeling/webhook.py:25-54`

No `X-Label-Studio-Signature` HMAC verification. Any caller can forge annotation events, potentially meeting annotation thresholds and triggering unintended retraining.

### C5. 8 Admin Services Exposed on 0.0.0.0 Without Authentication

**Perspectives**: Security
**Files**: `docker-compose.yml`

| Service | Port | Auth |
|---------|------|------|
| Prefect Server | 4200 | None |
| MLflow | 5000 | None |
| Prometheus | 9090 | None (+ `--web.enable-lifecycle`) |
| Pushgateway | 9091 | None |
| Redis | 6379 | None |
| PostgreSQL | 5432 | Weak default password |
| MinIO Console | 9001 | Weak default |
| Label Studio | 8081 | App-level only |

### C6. G5 Rollback Does Not Actually Rollback

**Perspectives**: Unimplemented, Integration
**Files**: `src/core/orchestration/flows/monitoring_flow.py:446-466`

`_trigger_rollback()` calls `POST /model/reload` which reloads the current `@champion` — a no-op if the champion IS the broken model. The code comment explicitly states: "A full version rollback ... is not yet implemented."

### C7. `SampleSelector` Entirely Unimplemented

**Perspectives**: Unimplemented
**Files**: `src/plugins/cv/__init__.py:17`, `src/core/orchestration/tasks/active_learning_tasks.py:81-109`

The Protocol is defined but CV plugin returns `None`. The active learning task has a hardcoded sort-by-uncertainty with no pluggable strategy. Diversity sampling (specified in design doc) is absent.

### C8. `PREFECT_API_URL` Not Configured for API Container

**Perspectives**: Integration
**Files**: `docker-compose.yml` (api service environment)

Without `PREFECT_API_URL`, Prefect defaults to `http://localhost:4200/api` inside the container. The webhook handler and admin endpoint both call `run_deployment()` which silently fails. Neither `.env.example` nor `docker-compose.yml` includes this variable for the `api` service.

### C9. Prometheus G4 Canary Gate Metric Name Mismatch

**Perspectives**: Integration
**Files**: `src/core/monitoring/canary_metrics.py:77-80`

Queries use `status=~"5.."` but `prometheus-fastapi-instrumentator` with `should_group_status_codes=True` emits `status="5xx"`. The regex never matches, so `canary_error` returns `None`, and the gate always passes with "Insufficient data — skipping check."

### C10. `active-learning` MinIO Bucket Not Created

**Perspectives**: Integration
**Files**: `docker/minio/entrypoint.sh:25-28`

The entrypoint creates 5 buckets but omits `active-learning`. All writes to `s3://active-learning/accumulated/` and `s3://active-learning/rounds/round_state.json` fail with `NoSuchBucket`.

---

## Major Findings

### Native Feature Utilization

| # | Issue | Files |
|---|-------|-------|
| N1 | Label Studio SDK bypassed for raw httpx — fragile to API changes | `active_learning/labeling/bridge.py` |
| N2 | Evidently: string-matching on raw metrics dict instead of typed API | `monitoring/evidently/drift_detector.py:66-84` |
| N3 | MLflow autolog + manual log_params overlap — duplicate param warnings | `plugins/cv/trainer.py:96-115` |
| N4 | FastAPI `app.state` bypasses `Depends()` — no type safety, hard to test | `serving/api/routes.py:30-35` |
| N5 | `time.sleep()` blocks Prefect worker thread in canary monitoring | `orchestration/flows/deployment_flow.py:152` |

### Service Integration

| # | Issue | Files |
|---|-------|-------|
| I1 | AL Prefect deployment never registered — `run_deployment()` will fail | `monitoring_flow.py:478` |
| I2 | `run_deployment()` called without `await` — coroutine discarded, never triggers | `monitoring_flow.py:431-443, 475-480` |
| I3 | Nginx canary config baked into image — container restart reverts to champion-only | `docker/nginx/Dockerfile:12` |
| I4 | `api-canary` Prometheus scrape target always active — error noise when canary is off | `configs/prometheus/prometheus.yml:15-18` |
| I5 | `DataValidator`/`ModelTrainer` not wired through plugin loader — direct CV imports | `orchestration/tasks/data_tasks.py:67-68` |
| I6 | `DriftConfig` requires S3 credentials with no default — fails if env vars missing | `monitoring/evidently/config.py:19-20` |

### Advanced Features

| # | Issue | Files |
|---|-------|-------|
| A1 | PyTorch: No AMP/mixed precision — 30-50% GPU speedup missed | `plugins/cv/trainer.py` |
| A2 | PyTorch: No LR scheduler — static LR for entire training | `plugins/cv/trainer.py:85-89` |
| A3 | Prometheus: No recording rules — expensive queries on every Grafana refresh | `configs/prometheus/prometheus.yml` |
| A4 | DVC: No `dvc.yaml` pipeline — only add/push/pull used | (absent from repo) |
| A5 | Prefect: All flows `retries=0`, no concurrency limits — concurrent CT corrupts data | All flow files, `serve.py` |
| A6 | MLflow: `mlflow.evaluate()` not used — single-metric champion comparison | `continuous_training_tasks.py` |
| A7 | Evidently: Only `DataDriftPreset` — no `TestSuite` or `DataQualityPreset` | `drift_detector.py` |
| A8 | GitHub Actions: No dependency caching, no Docker layer caching | `.github/workflows/ci.yml` |
| A9 | Grafana: Empty `templating.list` — no variables for job/model filtering | `mlops-overview.json:149` |

### UX Improvements

| # | Issue | Files |
|---|-------|-------|
| U1 | `/health` returns HTTP 200 even when model not loaded | `routes.py:38-42`, `schemas.py:54` |
| U2 | Grafana dashboard has zero Active Learning panels despite 4 AL metrics | `mlops-overview.json` |
| U3 | Alert contact point sends to `alerts@localhost` — all alerts silently dropped | `alerting/contact-points.yml:8-12` |
| U4 | `AWS_ACCESS_KEY_ID` required at runtime but absent from `.env.example` | `app.py:63,79` |
| U5 | `/model/reload` returns HTTP 500 for all failures including "not found" | `routes.py:176-181` |
| U6 | `api-canary` has no host port — direct canary inspection impossible | `docker-compose.yml:157-185` |

### Security & Stability

| # | Issue | Files |
|---|-------|-------|
| S1 | All containers run as root — no `USER` instruction in any Dockerfile | `docker/serving/Dockerfile` etc. |
| S2 | Redis has no password, port 6379 exposed on all interfaces | `docker-compose.yml:107-118` |
| S3 | No Docker network segmentation — flat bridge for all 12 services | `docker-compose.yml` |
| S4 | Serving Dockerfile uses unpinned `>=` deps, no lockfile | `docker/serving/Dockerfile:16-28` |
| S5 | No file type/size validation on `/predict` upload before PIL processing | `routes.py:66-70` |
| S6 | Prometheus `--web.enable-lifecycle` exposes unauthenticated reload/quit API | `docker-compose.yml:217` |
| S7 | CI pushes `:latest` Docker tag — violates CLAUDE.md Docker Rules | `.github/workflows/ci.yml:58` |
| S8 | Label Studio local file serving enabled — potential file disclosure risk | `docker-compose.yml:286-287` |

### Unimplemented Features

| # | Issue | Files |
|---|-------|-------|
| F1 | Grafana alerts → Prefect trigger chain missing — autonomous retraining broken | `alerting/contact-points.yml` |
| F2 | No type checking in CI despite required type hints policy | `.github/workflows/ci.yml` |
| F3 | ML CI report only logs output, does not compare against champion | `.github/workflows/ml-ci.yml:41-58` |
| F4 | Pseudo-label periodic audit (random sampling → human verification) absent | (no implementation) |
| F5 | Confidence Tracker component missing from monitoring pillar | `src/core/monitoring/` |
| F6 | AL and data accumulation Prefect deployments not registered | (no serve script) |

---

## Key Conclusion

**The Data Flywheel loop does not close end-to-end.** Three independent reasons:

1. **Image bytes not stored** — pseudo-labels have metadata only, retraining has no images
2. **Label Studio webhook not registered** — human labeling → retrain trigger path broken
3. **`run_deployment()` not awaited** — drift → retrain automatic trigger is a no-op

The platform's core value proposition (Closed-Loop Active Learning) is architecturally implemented but not operationally functional. Fixing C1, C3, and I2 would close the loop.

---

## Recommended Priority

### Phase 1: Close the Loop (C1, C3, I2)
- Store image bytes in S3 during auto-accumulation
- Register Label Studio webhook via setup script
- Fix `await run_deployment()` in monitoring flow

### Phase 2: Security Hardening (C2, C4, C5, S1-S3)
- Add auth to admin endpoints
- Add webhook signature verification
- Bind internal services to 127.0.0.1
- Add non-root users to Dockerfiles

### Phase 3: Operational Completeness (C6-C10)
- Implement real G5 rollback
- Implement `SampleSelector`
- Fix `PREFECT_API_URL`, G4 metric names, MinIO bucket creation

### Phase 4: Advanced Features & UX (A1-A9, U1-U6)
- Add AMP, LR scheduler, DVC pipelines
- Fix health endpoint, Grafana dashboard, alert routing
