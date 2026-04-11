# Platform Gap Analysis & 구현 로드맵

> **작성일**: 2026-04-10
> **최종 업데이트**: 2026-04-10 (Phase E-1 완료, E-2 부분 완료: S5 signature fix, E-3 부분 완료: Grafana 다중 채널 알림 베이스라인)
> **목적**: 업계 표준 MLOps 플랫폼(ZenML, ClearML, MLRun, Lightly.ai, Google MLOps Level 2) 대비 data-flywheel 플랫폼의 격차를 식별하고, 다중 세션에 걸친 구현 로드맵을 제시한다.

---

## 0. Quick Resume (다음 세션 착지 페이지)

> 이 섹션은 **매 세션 말미에 전면 재작성**한다. 다음 세션의 Claude는 `head -60` 만 읽고도 즉시 재개할 수 있어야 한다.
>
> **🔴 먼저 §0.5 【중요】 문서 유지 규칙을 읽었는가?** — 읽지 않았다면 지금 스크롤을 내려 §0.5 A~G 를 먼저 확인하고, 특히 C(End-of-Session 프로토콜)와 E(Anti-Patterns)는 반드시 숙지한 후 작업을 개시한다. 이 문서는 규칙 위반에 취약하며, 규칙 위반은 과거 세션의 기록을 소리 없이 손상시킨다.

- **Last updated**: 2026-04-11
- **Current phase**: **Phase E — Event-Driven & Operational Hardening** (우선순위 1)
- **Last commit on roadmap track**: `bd9cd13 docs(roadmap): E-2 runtime verification session log + resume pointer update` (branch `fix/phase-e2-al-flow-trigger-source`, 3-commit stack on top of main)
- **Latest completed units**:
  - E-2 runtime E2E + silent concealer 4곳 제거 (branch `fix/phase-e2-al-flow-trigger-source`) → §6-E2-runtime
  - E-3 베이스라인 (`b8c7f8a`) → §6-E3
  - E-2 서브태스크 S5 (PR #27, `9e92463`) → §6-E2-S5
  - E-1 전체 (PR #26, `ab3d14a`) → §6-E1
- **Next action (immediate)**: **api 이미지 의존성 결손 수정** — `docker/serving/Dockerfile` 에 `prefect` + `httpx` 추가 → Label Studio project 시드 → webhook → CT E2E 완주. narrow-catch 가 노출한 최대 가치 finding 이라 조기 처리 권장. 자세한 체크리스트는 §4 Phase E-2 Task Board 참조.
- **Secondary next**: E-3 잔여 — Prefect notification block 연동 (`orchestration_trigger_failure_total` counter 위에서 PromQL alert 발화) + Alert 4채널 E2E 발화 스모크. 상세는 §4 Phase E-3 Task Board 참조.
- **Known blocker**: (없음) docker 데몬 기동 환경에서 E-2 drift HIGH/MEDIUM 경로는 이번 세션에 완주됨.

### Verify state before resuming

```bash
# 1. Git state
git log --oneline -10

# 2. Unit regression (324 total; narrow-except + webhook regression 포함)
uv run pytest tests/unit -q

# 3. Silent concealer 회귀 체크 — `except Exception:` 이 다시 등장했는지 확인
grep -n "except Exception" src/core/orchestration/flows/monitoring_flow.py \
  src/core/active_learning/labeling/webhook.py
# 허용: docstring 내 역사 서술만. 실제 catch 구문이 있으면 regression.

# 4. Orchestration counter import chain — FastAPI-free 모듈에서 worker 로 접근 가능
python -c "from src.core.monitoring.orchestration_counter import ORCHESTRATION_TRIGGER_FAILURE_COUNTER; print('OK', ORCHESTRATION_TRIGGER_FAILURE_COUNTER._name)"

# 5. Drift fixture seeder 동작 미리 보기
uv run python -c "
from scripts.seed_drift_fixtures import _deterministic_medium_current
from scripts.run_evidently_demo import generate_prediction_data
from src.core.monitoring.evidently.drift_detector import detect_drift
ref = generate_prediction_data(n_samples=500, confidence_mean=0.88, confidence_std=0.08, seed=42)
curr = _deterministic_medium_current()
print('medium drift_score:', detect_drift(ref, curr)['drift_score'])  # 0.5 expected
"
```

### Open follow-up tickets (carried over across sessions)

- [ ] **[api 이미지 의존성 결손]** `docker/serving/Dockerfile` 에 `prefect` + `httpx` 추가. 현재 webhook 핸들러가 `ImportError` 로 silent no-op (narrow-catch 가 노출). Label Studio project 시드 + API key 세팅 후 webhook → CT E2E 완주. 출처: §6-E2-runtime. **우선순위: High** (Gate 2/3 quality gates 에서도 재확인됨 — webhook 경로가 역사적으로 한 번도 발화한 적 없음).
- [ ] **[serving `/model/reload` 422]** `_trigger_rollback()` 의 MLflow alias 이동은 성공하지만 serving 컨테이너 `/model/reload` 엔드포인트가 422 Unprocessable Entity 를 반환해 새 champion 이 실전 반영되지 않음. payload schema 확인 필요. 출처: §6-E2-runtime.
- [ ] **[`_run_async` 잔존자 감사]** `src/core/orchestration/flows/data_accumulation_flow.py` 에 아직 `_run_async(run_deployment(...))` 패턴이 남아 있을 가능성. 이는 E-2 runtime 에서 발견된 pre-existing ValueError(`asyncio.run(FlowRun)`) 버그와 동일한 형태이며, `data_accumulation_flow` 내부 catch 가 아직 bare `except Exception` 인지도 함께 감사. 출처: Gate 2 pr-reviewer finding (quality-gates pipeline run 2026-04-11). **우선순위: Medium** — data accumulation 경로도 silent 하게 깨져 있을 가능성.
- [ ] **[`orchestration_trigger_failure_total` 관측 표면 활성화]** `prometheus_client` 의 labeled counter 는 `.labels(...).inc()` 가 최소 1회 호출되기 전까지 `/metrics` 에 metric family 자체가 나타나지 않는다. 현재 api 컨테이너는 narrow-catch 경로를 밟기 전에 `ImportError` 로 먼저 탈출하므로 counter bump 라인에 도달한 적이 없음 → `curl /metrics | grep orchestration_trigger` 결과가 공란. wiring 자체는 정확하며 첫 실제 실패 시 즉시 노출됨. **조치 옵션**: (a) api 이미지 deps 수정(위 첫 항목) 후 자연 해소, (b) `metrics.py` 에서 모듈 로드 시 `0` 샘플을 한 번 prime 해두기 (`counter.labels(trigger_type="bootstrap", error_class="none").inc(0)`). Prefect notification block 연동 전에 반드시 먼저 해결. 출처: Gate 3 runtime-verifier finding (quality-gates pipeline run 2026-04-11).
- [ ] **[Alert 발화 E2E]** docker compose 환경에서 drift/error rate/latency 임계치를 인위적으로 하향 → Grafana 4채널(Email/Slack/Generic Webhook/PagerDuty) 동시 수신 확인. 출처: §6-E3, Gap 7.
- [ ] **[Prefect notification block]** Quality gate 실패(G1~G5) → Prefect notification block 연동. 이제 `orchestration_trigger_failure_total{trigger_type,error_class}` counter 가 있어 PromQL → notification block 경로가 가능. **전제 조건**: 위 "관측 표면 활성화" 티켓 해결 (counter 가 실제로 `/metrics` 에 노출되는 상태여야 PromQL alert 가 발화할 수 있음). 출처: Gap 7 잔여, §6-E3.

---

## 0.5. 🔴 【중요】 문서 유지 규칙 (Maintenance Protocol)

> **⚠️ CRITICAL — 이 섹션은 반드시 먼저 읽는다.**
>
> 이 문서는 **세션 간 핸드오프**가 주목적이다. 이 섹션의 규칙을 지키지 않으면:
> - §6 Session Log 가 소리 없이 손상되고 (과거 세션의 증거가 왜곡됨),
> - §0 Quick Resume 이 stale 해지고 (다음 세션이 잘못된 지점에서 재개함),
> - §3 Gap 카탈로그와 §6 Session Log 가 다시 뒤섞여 (최초 재구조 이전 상태로 회귀함).
>
> **규칙은 짧다 — §0.5 A~G 를 끝까지 읽고 C(End-of-Session 프로토콜)와 E(Anti-Patterns)는 암기한다.** 작업을 시작하기 전에 본 섹션을 스킵하지 말 것. 스킵했다면 반드시 이 섹션으로 돌아와 확인한 뒤 재개한다.

아무도 "전체를 다시 읽고 정리" 하지 않아도, 매 세션이 작은 규칙만 지키면 문서가 **자가 정리**되도록 설계되어 있다. 아래 규칙을 따른다.

### 섹션별 수명 (Section Lifecycle)

| 섹션 | 수명 | 누가 갱신 | 언제 갱신 | 어떻게 |
|---|---|---|---|---|
| §0 Quick Resume | 세션 단위 전면 재작성 | 세션 끝낼 때 Claude | 마지막 단계 | 이전 블록 **덮어쓰기** (append 아님) |
| §0.5 Maintenance Protocol | 거의 불변 | 프로세스를 바꿀 때만 | 드물게 | Edit |
| §1~§2 (현황·벤치마크) | 플랫폼 레벨, 거의 불변 | 새 플랫폼/서비스 추가 시 | 드물게 | Edit |
| §3 Gap 카탈로그 | 정적 참조 | 새 Gap 식별 시에만 | 드물게 | 새 Gap 블록 append (번호 이어서) |
| §4 Task Board | 태스크 단위 토글 | 태스크 완료 시 | 즉시 | 해당 체크박스만 토글 + 취소선 + §6 앵커 |
| §6 Session Log | **append-only** | 세션 종료 시 | 매 세션 | 기존 블록 **절대 수정 금지**, 새 블록 추가만 |
| §7 References | 거의 불변 | 새 레퍼런스 발견 시 | 드물게 | Edit |

### A. 새 세션을 시작할 때 (Resume 프로토콜)

1. `head -60 docs/roadmap-platform-gaps.md` 로 §0 Quick Resume 만 읽는다.
2. **Next action** 과 **Open follow-up tickets** 를 확인한다.
3. `Verify state before resuming` 의 명령을 **그대로 실행**하여 문서가 기술하는 상태가 실제로 유효한지 확인한다. 불일치 발견 시 해당 필드를 §0에서 즉시 수정하고 §6 에 불일치 사유를 기록한 후 재개한다 (stale memory 원칙).
4. 관심 있는 Gap 의 배경이 필요하면 §3 의 해당 Gap 블록으로 점프, 세부 진척이 필요하면 각 Gap 말미의 "→ 진행 로그: §6-EN" 링크를 따라간다.

### B. 작업 중 (In-Session)

- Gap 카탈로그(§3) 본문을 **수정하지 않는다**. Gap 의 "현상/업계 기준/필요 조치" 는 고정이다. 예외: 해당 Gap 의 업계 기준 자체가 변했을 때.
- Task Board(§4) 체크박스는 **완료 즉시** 토글한다 — 세션 말미까지 미루지 않는다. 토글할 때 항상 다음 형태:
  - `- [x] ~~작업 설명~~ → §6-XN`
- 새로 발견한 latent failure, follow-up, 또는 silent bug 는 그 자리에서 §0 `Open follow-up tickets` 에 한 줄 추가한다. 잊기 전에.

### C. 세션을 끝낼 때 (End-of-Session 프로토콜)

**반드시 이 순서로**:

1. **§6 Session Log 에 신규 블록 append**. 블록 ID 규칙 `6-<Phase><Order>[-<Subtask>]` (예: `6-E2-S7`, `6-F1`, `6-G3`). 고정 포맷 필드 전부 채우기:
   - Commit / PR / Gap / Scope
   - Problem (latent failure 가 있었다면)
   - Changes (체크박스 bullet, [x]=이번 블록에서 완료, [ ]=후속)
   - Files changed (경로 + 한 줄 설명)
   - 설계 원칙 (있다면)
   - Verification (Unit / Lint / Review / Runtime 별로)
   - Unblocked (어떤 후속 작업의 전제가 해제됐는지)
   - Remaining for parent phase → §4 링크
   - New follow-up (§0 로 carry-over 하는 항목)
2. **§4 Task Board 에서 해당 체크박스 토글** (취소선 + `→ §6-XN` 앵커).
3. **§0 Quick Resume 전면 재작성**:
   - `Last updated` 날짜 갱신
   - `Last commit on roadmap track` 해시/제목 갱신
   - `Latest completed units` 에 이번 세션의 `6-XN` 추가 (오래된 항목은 제거 가능)
   - `Next action` 을 다음 세션이 할 일로 교체
   - `Open follow-up tickets` 에서 해결된 항목 제거, 신규 항목 추가
   - `Verify state before resuming` 명령이 여전히 유효한지 확인, 필요 시 갱신
4. **정적 검증 5종 실행** (§0.5 D 참조). 실패 시 내용 유실 — 백업에서 복구 후 재시도.
5. **커밋**: `docs(roadmap): <phase>-<task> session log + resume pointer update`
   - 예: `docs(roadmap): E-2 webhook→CT verification session log + resume pointer update`

### D. 내용 보존 검증 (Regression Guard)

재구조·이동 작업 전에 항상 원본을 `/tmp/roadmap-platform-gaps.backup.md` 로 백업한 후 아래 5종 명령으로 검증한다:

```bash
# 1. 라인 수는 동일 또는 증가 (Session Log append 때문에 증가가 정상)
wc -l /tmp/roadmap-platform-gaps.backup.md docs/roadmap-platform-gaps.md

# 2. 알려진 커밋 해시 모두 존재
grep -c "ab3d14a\|9e92463\|b8c7f8a" docs/roadmap-platform-gaps.md  # ≥ 기존 카운트

# 3. PR 번호 모두 존재
grep -c "PR #26\|PR #27" docs/roadmap-platform-gaps.md  # ≥ 기존 카운트

# 4. 섹션 스켈레톤 무결 (§0, §0.5, §1~§7)
grep -n "^## " docs/roadmap-platform-gaps.md

# 5. Gap 1~10 헤더 모두 존재
grep -c "^### Gap " docs/roadmap-platform-gaps.md  # 반드시 10
```

**Unique phrase spot-check**: 재구조 후 다음 페이지 크기의 phrase 목록을 백업 대비 `grep -c` 로 비교해 모두 `backup ≤ new` 인지 확인한다. 예시 목록은 최근 재구조 세션(§6-(없음), 최초 정리 세션)에서 사용한 16개 phrase 를 참조.

### E. Anti-Patterns (금지 사항)

- ❌ **§6 기존 블록 수정** — 과거 세션의 로그는 불변. 틀린 내용을 발견해도 새 블록(`6-XN-correction`)을 추가해서 정정한다.
- ❌ **§3 Gap 본문에 진척 서술 추가** — Gap 은 정적 참조 문서. 진척은 반드시 §6 로 간다.
- ❌ **Gap 카탈로그에서 Gap 번호 재사용·재번호** — 기존 번호는 영구적. 새 Gap 은 `Gap 11`, `Gap 12` 로 이어서 추가.
- ❌ **§4 Task Board 에 세부 커밋 메시지나 변경 파일 목록 붙이기** — 체크박스 한 줄 + §6 앵커 한 줄이 전부. 상세는 §6 에만.
- ❌ **§0 Quick Resume 에 히스토리 누적** — `Latest completed units` 는 최근 3~5개만 유지. 오래된 항목은 제거 (§6 에 이미 보존돼 있음).
- ❌ **원본 삭제 없이 재작성** — 재구조 작업은 반드시 백업(`/tmp/`) → 검증 명령 5종 통과 순서.
- ❌ **"요약" 또는 "정리 차원에서 삭제"** — 내용 보존이 1순위. 문서가 길어지는 것은 허용, 정보 손실은 불허.

### F. 새 Phase 추가 절차

Phase E 가 종료되고 Phase F/G/H 로 넘어갈 때:

1. §4 에 해당 Phase 표는 이미 존재함 (F/G/H placeholder). Task Board 체크리스트만 각 작업별로 추가.
2. §0 Quick Resume 의 `Current phase` 를 새 Phase 로 교체.
3. 새 Phase 첫 세션 종료 시 §6 에 `6-F1` 형태로 블록 append.
4. 해당 Phase 완료 시 §2 업계 벤치마킹 표의 관련 기능 셀 상태 갱신 (⚠️ → ✅ 등).

### G. 문서 재구조가 필요할 때

다음 세션 핸드오프가 실제로 실패하기 시작하면 (예: §6 가 50개 블록 넘게 누적되어 스크롤 부담) 재구조를 고려한다. 그 때의 원칙:

1. `/tmp/` 백업 필수.
2. **이동만, 삭제 없음**. "요약" 은 금지.
3. 섹션별 수명 원칙(위 표)을 유지. 수명이 다른 내용은 섞지 않는다.
4. `§0.5 D` 의 5종 검증 + unique phrase spot-check 필수.
5. 재구조 자체도 §6 에 블록으로 기록 (`6-meta-restructure-YYYY-MM-DD`).

---

## 1. 현재 상태 요약

data-flywheel은 Active Learning-First Closed-Loop MLOps 플랫폼으로, 4개 Phase(A~D)를 거쳐 핵심 구조가 구현되었다:

- **Phase A**: Active Learning Core (uncertainty estimation, confidence routing, pseudo-label accumulation, Label Studio bridge)
- **Phase B**: Continuous Training Loop (event-driven retrain, champion gate, data integration)
- **Phase C**: CI/CD & Deployment (GitHub Actions, CML, canary deploy, rollback)
- **Phase D**: Architecture Refactoring (core/plugins 분리, Protocol interfaces)

**12개 Docker 서비스**: PostgreSQL, MinIO, MLflow, Prefect Server, Redis, API, API-Canary, Nginx, Prometheus, Pushgateway, Grafana, Label Studio

**6개 Prefect Flow**: training, continuous-training, monitoring, active-learning, data-accumulation, deployment

---

## 2. 업계 벤치마킹 비교

### 비교 대상

| 플랫폼 | 특징 |
|--------|------|
| **ZenML** | Pipeline-as-code, artifact lineage 자동 추적, 모듈식 orchestrator/deployer 교체 |
| **ClearML** | End-to-end MLOps suite, experiment tracking, data versioning, pipeline orchestration 통합 |
| **MLRun** | Iguazio 기반, Kubernetes-native, real-time serving graph, feature store 내장 |
| **Lightly.ai** | Active Learning 전문, embedding 기반 diversity selection, coreset/typicality selection |
| **Google MLOps Level 2** | CI/CD pipeline 완전 자동화, event-driven retrain, 품질 검증 자동화 |

### 기능별 비교표

| 기능 | data-flywheel | ZenML | ClearML | Lightly.ai | MLRun | Google L2 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| Closed-Loop Retrain | ✅ | ⚠️ Partial | ✅ | ✅ | ✅ | ✅ |
| Event-Driven Triggers | 🟢 **대부분 완료** (E-1 + E-2 drift HIGH/MEDIUM 런타임 PASS; webhook 경로는 api 이미지 의존성 결손 후속) | ✅ | ✅ | N/A | ✅ | ✅ |
| Canary Deploy | ⚠️ Partial | ✅ (Seldon) | N/A | N/A | ✅ (Nuclio) | ✅ |
| Shadow Deploy | ❌ | ✅ (Seldon) | N/A | N/A | ✅ | ✅ |
| A/B Testing | ❌ | ✅ (Seldon) | N/A | N/A | ✅ | ✅ |
| Active Learning | ✅ | ⚠️ Plugin | ⚠️ Plugin | ✅ **Core** | N/A | N/A |
| Embedding Diversity | ❌ | N/A | N/A | ✅ **Core** | N/A | N/A |
| Drift Detection | ✅ | ✅ (Evidently) | ✅ | N/A | ✅ | ✅ |
| Feature Store | ❌ | ✅ (Feast) | ⚠️ | N/A | ✅ **Core** | ✅ (Vertex) |
| Data Lineage | ⚠️ Partial | ✅ **Core** | ✅ | N/A | ✅ | ✅ |
| Alerting/Notification | ⚠️ **Partial** (E-3 베이스라인 완료) | ✅ (Notifier) | ✅ | N/A | ✅ | ✅ |
| Multi-Model Serving | ❌ | ✅ | ✅ | N/A | ✅ | ✅ |
| Plugin/Domain Agnostic | ✅ Protocol | ⚠️ | ❌ | ❌ CV-only | ⚠️ | ✅ |

**범례**: ✅ 완전 구현 | ⚠️ 부분 구현 | ❌ 미구현 | N/A 해당 없음

---

## 3. Gap 카탈로그

> 이 섹션은 **Gap 의 배경·업계 기준·필요 조치만** 담는 정적 참조 문서다. 세션별 진척은 모두 §6 Session Log 에 기록한다. 각 Gap 말미의 "진행 로그" 링크가 해당 진척 블록을 가리킨다.

### Gap 1: Event-Driven Automation 부재 (Critical → Partial) 🟠

**원래 현상**: Core Philosophy #3 "Event-Driven Automation"을 명시하지만, 실제 event-driven 트리거가 부재.

**업계 기준**: Google L2, ZenML, MLRun 모두 cron 기반이 아닌 event 기반(webhook, drift, annotation 완료)으로 retrain 파이프라인을 자동 발화한다. Prefect 자체가 event/deployment 기반 트리거를 지원하므로 인프라 레벨의 장벽은 없고, 통합된 worker + 4개 flow deployment 등록이 핵심이다.

**필요 조치** (요약): Prefect worker 통합 serve 엔트리포인트, CT/AL/monitoring/data-accumulation 4개 flow deployment 등록, webhook/drift 기반 런타임 E2E 발화 검증, `active_learning_flow` signature 정합.

**현 상태**: **대부분 완료** — E-1 전체(4 deployments), E-2 S5(signature), drift HIGH E2E(rollback + CT 자동), drift MEDIUM E2E(AL + CT 병행) 모두 런타임 PASS. 잔여는 Label Studio webhook 경로의 **api 이미지 의존성 결손** 후속 작업 1건 뿐. Gap 1 의 본질(event-driven trigger 의 실제 동작)은 이번 세션으로 증명됨.

**남은 작업량**: 0.5 세션 (`docker/serving/Dockerfile` 에 prefect+httpx 추가 + Label Studio project 시드 + webhook E2E 완주)

**→ 진행 로그**:
- §6-E1 — Prefect Worker 통합 serve_all + 4 deployments
- §6-E2-S5 — `active_learning_flow` signature 정합 (silent no-op 해소)
- §6-E2-runtime — Drift HIGH/MEDIUM 런타임 E2E 완주 + silent concealer 4곳 제거 + pre-existing latent 버그 3개 노출/수정

---

### Gap 2: Canary Deployment Docker exec 의존 (High) 🟠

**현상**: `deployment_tasks.py`의 canary 로직이 `subprocess`로 `docker compose` CLI를 호출. Nginx upstream 갱신도 `docker exec`로 sed 명령 실행.

- Docker-in-Docker 없이 호스트 Docker 소켓 필요 (보안 위험)
- Nginx reload가 atomic하지 않음 (중간 상태에서 요청 실패 가능)
- 테스트 환경에서 재현이 어려움

**업계 기준**: ZenML은 Seldon/KServe 기반 canary를, MLRun은 Nuclio serving graph를 사용하여 컨테이너 오케스트레이터 레벨에서 canary를 수행.

**필요 조치**:
- [ ] Nginx upstream 관리를 template + signal 방식으로 변경
- [ ] Canary 컨테이너 관리를 Docker SDK for Python 또는 compose profile로 변경
- [ ] G4 canary gate에 실제 traffic 비교 로직 E2E 검증
- [ ] Canary rollback 자동화 테스트 추가

**예상 작업량**: 2 세션

---

### Gap 3: A/B Testing & Shadow Deployment 미구현 (Medium) 🟡

**현상**: Canary deployment만 존재. A/B testing (user segment 기반 traffic split)과 shadow deployment (champion 결과만 반환, challenger는 로깅만) 미구현.

**업계 기준**: Google L2, ZenML(Seldon), MLRun 모두 shadow mode와 A/B testing 지원. Shadow deploy는 새 모델의 실전 성능을 위험 없이 평가하는 핵심 기법.

**필요 조치**:
- [ ] Shadow mode: predict 시 champion + challenger 모두 실행, champion 결과만 반환
- [ ] Shadow prediction 결과를 별도 S3 키에 로깅
- [ ] A/B test: Nginx header-based routing (`X-Experiment-Group`)
- [ ] Shadow/A/B 결과 비교 Grafana dashboard panel 추가
- [ ] Shadow deploy E2E 테스트

**예상 작업량**: 2~3 세션

---

### Gap 4: Embedding 기반 Diversity Selection 미구현 (Medium) 🟡

**현상**: `UncertaintyDiversitySelector`가 uncertainty score (1D float)의 거리만으로 diversity 계산. 실제 production active learning은 embedding space에서의 diversity가 필수.

**업계 기준**: Lightly.ai는 self-supervised learning embedding + coreset selection(k-center greedy)을 핵심으로 제공. Typicality-based selection으로 대표성/비정형 데이터 구분. Embedding 기반 diversity로 1,000개 선별 이미지가 recall +32%, F1 +10% 향상 사례.

**필요 조치**:
- [ ] 모델 penultimate layer에서 embedding 추출 기능 (CV plugin)
- [ ] Embedding storage: 예측 시 embedding을 S3/Redis에 캐싱
- [ ] Coreset selection (k-center greedy) in embedding space
- [ ] BADGE sampling (Bayesian Active Learning by Disagreement in Gradient Embedding) 추가
- [ ] Typicality-based selection 옵션 추가
- [ ] Embedding diversity selector를 Plugin protocol로 추상화

**예상 작업량**: 3~4 세션

---

### Gap 5: Feature Store 부재 (Medium) 🟡

**현상**: Prediction 시 feature engineering이 단순 image transform만. 메타데이터를 체계적으로 관리하는 feature store가 없음. Reference data와 current data 비교가 하드코딩된 column 이름에 의존.

**업계 기준**: MLRun은 feature store 내장, ZenML은 Feast 통합, Google Vertex AI는 Vertex Feature Store 제공. Feature store는 training-serving skew 방지와 feature 재사용의 핵심.

**필요 조치**:
- [ ] Feast 또는 Redis 기반 lightweight feature store 도입 검토
- [ ] Prediction log schema 표준화 (Pydantic model)
- [ ] Feature versioning과 training-serving consistency 보장
- [ ] Drift detection에서 feature store 참조로 전환

**예상 작업량**: 2~3 세션

---

### Gap 6: Data Lineage & Reproducibility 불완전 (Medium) 🟡

**현상**: DVC로 데이터 버전 관리하고 MLflow에 hash를 tag하지만:
- 어떤 prediction log들이 training data로 merge되었는지 추적 불가
- Pseudo-label vs human-label 비율이 MLflow run에 미기록
- 특정 모델이 어떤 AL round의 데이터로 학습되었는지 역추적 번거로움

**업계 기준**: ZenML은 모든 artifact에 자동 lineage 추적이 핵심 기능. ClearML도 data versioning + experiment lineage 통합 제공.

**필요 조치**:
- [ ] MLflow run에 data lineage metadata 체계적 기록
  - source_counts: {pseudo_label: N, human_label: M, original: K}
  - al_round: int
  - data_hash: str
  - merged_from: list[str] (S3 keys)
- [ ] Prefect artifact에 lineage chain 기록
- [ ] Lineage 조회 API 또는 CLI 추가
- [ ] Lineage visualization (Grafana 또는 별도 UI)

**예상 작업량**: 2 세션

---

### Gap 7: 알림(Alerting) 시스템 미구현 (Medium → Partial) 🟡

**원래 현상**: Grafana alerting 설정 파일이 있지만, 실제 notification channel이 미설정. Quality gate 실패 시 로깅만 수행.

**업계 기준**: ZenML Notifier, ClearML alerting, MLRun, Google L2 모두 다중 채널(email/Slack/PagerDuty) + severity 기반 라우팅을 기본 제공. 단일 채널 의존은 운영 시 단일 장애점(SPOF)이 된다.

**필요 조치** (잔여):
- [ ] Quality gate failure → Prefect notification block 연동 (후속)
- [ ] Alert firing E2E 테스트 (docker compose 환경에서 임계치 인위 하향 → 4채널 발화 확인)

**현 상태**: **Partial** — Grafana 4채널 contact point + severity routing 베이스라인 완료. Prefect notification block 연동과 런타임 E2E 발화 검증은 대기.

**남은 작업량**: 0.5~1 세션 (Prefect notification block + E2E 발화 검증)

**→ 진행 로그**: §6-E3 — Grafana 다중 채널 알림 베이스라인

---

### Gap 8: Multi-Model Serving (Low) 🟢

**현상**: `registered_model_name` 하나만 관리. 여러 모델 동시 서빙이나 모델 간 dependency 관리 미지원.

**필요 조치**:
- [ ] Multi-model serving endpoint (path-based: `/predict/{model_name}`)
- [ ] Model dependency graph 정의
- [ ] Per-model quality gate 설정
- [ ] Model ensemble 옵션

**예상 작업량**: 2~3 세션

---

### Gap 9: Rate Limiting & Authentication (Low) 🟢

**현상**: Predict endpoint 인증 없이 공개. Admin endpoint만 API key 보호.

**필요 조치**:
- [ ] Nginx level rate limiting (`limit_req_zone`)
- [ ] API key 또는 JWT authentication for predict endpoint
- [ ] Per-client rate limiting 및 usage tracking
- [ ] API usage metrics → Prometheus

**예상 작업량**: 1 세션

---

### Gap 10: Plugin Dynamic Loading 미완성 (Low) 🟢

**현상**: `plugins/loader.py`가 환경 변수 기반이지만, `app.py`에서 `SoftmaxEntropyEstimator` 직접 import.

**필요 조치**:
- [ ] Protocol 기반 dynamic loading 완성
- [ ] Plugin registry pattern (entry_points 또는 config-based)
- [ ] 설정만으로 CV/NLP/Tabular 전환 가능하게
- [ ] Plugin 설치/활성화 CLI

**예상 작업량**: 1~2 세션

---

## 4. 구현 로드맵 Task Board

> 각 Phase 표 하위의 **Task Board 체크리스트**는 세션 단위로 토글한다. 완료된 항목은 ~~취소선~~ + §6 Session Log 앵커로 교차 참조한다. 세부 커밋·변경 파일·검증 결과는 §6 에서만 관리한다.

### Phase E: Event-Driven & Operational Hardening (우선순위 1)

| 순서 | 작업 | Gap | 예상 세션 | 상태 |
|:---:|------|:---:|:---:|:---:|
| E-1 | Prefect Worker 통합 serve_all & 4개 Deployment 등록 | Gap 1 | 1 | ✅ **완료** (PR #26, `ab3d14a`) |
| E-2 | Event-Driven Trigger E2E 검증 (webhook → CT, drift → CT/AL) + S5 signature fix | Gap 1 | 1~2 | 🟢 **대부분 완료** (S5 + drift HIGH + drift MEDIUM 모두 PASS; webhook E2E 는 api 이미지 의존성 결손으로 partial) |
| E-3 | Alerting 시스템 구축 (Grafana + Prefect notifications) | Gap 7 | 1~2 | 🟡 **부분 완료** (Grafana 4채널 베이스라인 OK, Prefect block + E2E 대기) |
| E-4 | Rate Limiting & API Authentication | Gap 9 | 1 | ⏳ 대기 |

**완료 기준**: `docker compose up` 후 Label Studio annotation 완료 → 자동 CT 트리거 → 모델 갱신까지 수동 개입 없이 동작. Alert 발생 시 Slack 알림.

#### E-1 Task Board

- [x] ~~`docker-compose.yml` `prefect-worker` 서비스 통합 `serve_all` 엔트리포인트 전환~~ → §6-E1
- [x] ~~Flow deployment 자동 등록 startup script (`src/core/orchestration/flows/serve_all.py`)~~ → §6-E1
- [x] ~~CT / AL / monitoring / data-accumulation 4개 flow 모두 RunnerDeployment 로 등록~~ → §6-E1
- [x] ~~Latent broken link 해소 확인 (`monitoring_flow._trigger_active_learning_pipeline()` → worker 도달)~~ → §6-E1

#### E-2 Task Board

- [x] ~~S5: `active_learning_flow` 에 `trigger_source: str = "manual"` 인자 추가 + summary 전파 + 회귀 테스트 2건~~ → §6-E2-S5
- [~] Label Studio annotation webhook → `continuous-training-deployment` 런타임 발화 검증 (docker compose up 필요) — **Partial**: route 200 OK 확인 + narrow-catch 가 pre-existing `ModuleNotFoundError` 노출. 실제 deployment 발화는 api 이미지 의존성 추가 후속 티켓으로 분리 → §6-E2-runtime
- [x] ~~Drift HIGH 감지 → `continuous-training-deployment` 자동 트리거 + MLflow rollback 체인 검증~~ → §6-E2-runtime
- [x] ~~Drift MEDIUM 감지 → `active-learning-deployment` + `continuous-training-deployment` 병행 트리거 검증 (S5 해제로 이제 가능)~~ → §6-E2-runtime
- [x] ~~**알려진 follow-up 티켓**: `_trigger_active_learning_pipeline()` 의 bare `except Exception:` 을 `ImportError` + `PrefectException` 으로 좁히고 실패 시 `log.ERROR` 또는 metric 승격 (silent failure concealer 제거)~~ → §6-E2-runtime (4곳 모두 좁힘, `orchestration_trigger_failure_total` counter 신설)

#### E-3 Task Board

- [x] ~~`configs/grafana/alerting/contact-points.yml` 4종 integration × 2 contact point 재작성 (`default-multi`, `critical-escalation`)~~ → §6-E3
- [x] ~~Alert rule 템플릿화 확인 (`configs/grafana/alerting/alerts.yml` 의 3개 rule + severity 라벨)~~ → §6-E3
- [x] ~~G5 HIGH severity → PagerDuty-style escalation (`configs/grafana/alerting/notification-policies.yml` 의 `severity = critical` matcher + `continue: true`)~~ → §6-E3
- [x] ~~Compose 환경 변수 포워딩 (`GF_SMTP_*` + `GRAFANA_*` + `.env.example` alerting 블록)~~ → §6-E3
- [ ] Quality gate failure → Prefect notification block 연동 (후속)
- [ ] Alert firing E2E 테스트 (docker compose 환경에서 임계치 인위 하향 → 4채널 발화 확인)

#### E-4 Task Board

- [ ] Nginx level rate limiting (`limit_req_zone`)
- [ ] API key 또는 JWT authentication for predict endpoint
- [ ] Per-client rate limiting 및 usage tracking
- [ ] API usage metrics → Prometheus

### Phase F: Advanced Active Learning (우선순위 2)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| F-1 | Embedding 추출 (CV plugin, penultimate layer) | Gap 4 | 1 |
| F-2 | Embedding Storage (S3/Redis caching) | Gap 4 | 1 |
| F-3 | Coreset Selection (k-center greedy) | Gap 4 | 1~2 |
| F-4 | BADGE / Typicality-based Selection | Gap 4 | 1 |

**완료 기준**: Active Learning pipeline이 embedding space에서 diversity-aware sample selection 수행. Selection quality metric 개선 검증.

### Phase G: Deployment Sophistication (우선순위 3)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| G-1 | Canary Deploy 리팩터링 (Docker SDK / compose profile) | Gap 2 | 1 |
| G-2 | Nginx Template + Signal 기반 upstream 관리 | Gap 2 | 1 |
| G-3 | Shadow Deployment 구현 | Gap 3 | 1~2 |
| G-4 | A/B Testing (header-based routing) | Gap 3 | 1 |

**완료 기준**: Canary, shadow, A/B 세 가지 deployment strategy가 설정으로 전환 가능. 각 전략의 E2E 테스트 통과.

### Phase H: Data & Feature Management (우선순위 4)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| H-1 | Data Lineage 체계화 (MLflow metadata + Prefect artifact) | Gap 6 | 1~2 |
| H-2 | Feature Store 도입 (Feast or Redis) | Gap 5 | 2~3 |
| H-3 | Multi-Model Serving | Gap 8 | 2~3 |
| H-4 | Plugin Dynamic Loading 완성 | Gap 10 | 1~2 |

**완료 기준**: 모든 모델에 대해 training data → model → prediction 역추적 가능. Feature store에서 training/serving 동일 feature 보장.

---

## 5. 우선순위 결정 기준

1. **Core Philosophy 충족도**: Gap 1(Event-Driven)은 5대 원칙 중 하나를 직접 위반하므로 최우선
2. **운영 안정성**: Gap 7(Alerting)은 production 운영의 기본 — 문제 발생 시 인지 불가
3. **차별화 가치**: Gap 4(Embedding Diversity)는 Lightly.ai 수준의 AL 품질 달성에 필수
4. **리스크 감소**: Gap 2(Canary)는 보안 위험(Docker 소켓 노출)과 배포 안정성 직결
5. **장기 확장성**: Gap 5, 8, 10은 플랫폼 성장에 따라 점진적 도입

---

## 6. Session Log (append-only)

> **규칙**:
> 1. **append-only** — 기존 블록은 수정·삭제하지 않는다. 새 세션은 아래에 새 블록을 추가한다.
> 2. **고정 포맷** — 각 블록은 Commit / PR / Gap / Scope / Changes / Files changed / Verification / Unblocked / Remaining / New follow-up 필드를 가능한 한 모두 채운다.
> 3. **앵커 ID** — `6-<Phase><Order>[-<Subtask>]` 규칙 (예: `6-E1`, `6-E2-S5`, `6-F1`). §0 Resume Pointer 와 §3 Gap 카탈로그와 §4 Task Board 가 이 ID 를 참조한다.

---

### 6-E1 · Phase E-1 완료 (2026-04-10)

- **Commit**: `ab3d14a feat(orchestration): unify prefect worker to serve all four core flows (#26)`
- **PR**: #26
- **Gap**: Gap 1 (Event-Driven Automation)
- **Scope**: Prefect worker 를 단일 CT deployment serve 에서 통합 `serve_all` 엔트리포인트로 전환하고, CT / AL / monitoring / data-accumulation 4개 core flow 를 RunnerDeployment 로 등록.

- **Changes**:
  - [x] `docker-compose.yml` 에 `prefect-worker` 서비스 추가 (원래부터 존재하되 CT 단일 deployment 만 서브) → 통합 `serve_all` 엔트리포인트로 전환
  - [x] Flow deployment 자동 등록 startup script 작성 (`src/core/orchestration/flows/serve_all.py`, 단일 `prefect.serve(...)` 호출)
  - [x] **CT, AL, monitoring, data-accumulation 4개 flow 모두 RunnerDeployment 로 등록**
    - `continuous-training-deployment` (event-driven)
    - `active-learning-deployment` (event-driven)
    - `monitoring-deployment` (cron `0 3 * * *`, daily)
    - `data-accumulation-deployment` (cron `0 */6 * * *`)
  - [x] **Latent broken link 해소 확인**: `monitoring_flow._trigger_active_learning_pipeline()` 이 호출하던 `run_deployment("active-learning-pipeline/active-learning-deployment")` 가 실제로 worker 에 도달 — 런타임 검증에서 `fetch-uncertain-predictions` + `select-samples-for-labeling` 이 `Completed()` 상태로 실행됨 (이전에는 silent no-op).

- **Files changed**: 7 files (+371 / −115)
  - 신규: `src/core/orchestration/flows/serve_all.py`, `tests/unit/test_orchestration_serve_all.py`
  - 수정: `docker/orchestration/Dockerfile` (image 0.2.0, pandas/evidently/scikit-learn 추가, ENTRYPOINT 교체), `docker-compose.yml` (prefect-worker env/depends_on 확장), `src/core/monitoring/metrics.py` + `src/core/serving/gunicorn/config.py` (pre-existing lint fix 동반)
  - 삭제: `src/core/orchestration/flows/continuous_training_serve.py` (단일 CT serve 엔트리포인트, 통합본으로 대체)

- **Verification**:
  - Unit: 316/316 pass (신규 5개 serve_all 테스트 포함)
  - Runtime: Prefect API 에 4개 deployment 정확한 이름/크론으로 등록, AL deployment 트리거 → worker 가 flow run pick up → `fetch-uncertain-predictions` + `select-samples-for-labeling` `Completed()` 도달
  - CI: Lint (Ruff) ✓, Unit Tests ✓

- **Unblocked**: Phase E-2 런타임 E2E 검증의 전제(worker 에 deployment 가 실제 등록됨)가 해제됨.
- **Remaining for parent phase (E-2 런타임 E2E)**: → §4 Phase E Task Board 참조.
- **New follow-up**: 없음.

---

### 6-E2-S5 · Phase E-2 서브태스크 S5 부분 완료 (2026-04-10)

- **Commit**: `9e92463 fix(orchestration): accept trigger_source in active_learning_flow (Phase E-2 S5) (#27)`
- **PR**: #27
- **Gap**: Gap 1 (Event-Driven Automation)
- **Scope**: Phase E-2 의 S5 서브태스크 = `active_learning_flow` signature 정합. Event-driven trigger 의 런타임 E2E 검증(webhook → CT, drift → CT/AL)은 별도 세션으로 분리.

- **Problem (latent silent failure)**: `monitoring_flow._trigger_active_learning_pipeline()` 이 `run_deployment(..., parameters={"trigger_source": "g5_medium_drift"})` 로 AL deployment 를 호출하지만, `active_learning_flow` signature 에 `trigger_source` 인자가 부재하여 Prefect 가 unknown-kwarg 로 거부. 호출부의 `try/except Exception` 이 예외를 삼키면서 G5 MEDIUM drift → AL 트리거 경로가 **로그만 WARNING, 기능은 무음 실패** 상태로 운영되고 있었음.

- **Files changed**:
  - `src/core/orchestration/flows/active_learning_flow.py` — `trigger_source: str = "manual"` 인자 추가 (CT flow 대칭 패턴), entry log, summary dict(두 분기) + markdown artifact 전파. Prefect UI 에서 "왜 이 AL run 이 생성되었는지" 추적 가능.
  - `tests/unit/test_active_learning_flow.py` — 회귀 테스트 2건 (`test_flow_accepts_trigger_source_and_propagates_to_summary`, `test_flow_trigger_source_defaults_to_manual_on_empty_path`).

- **Verification**:
  - Unit: 47/47 orchestration tests pass (신규 2건 포함)
  - Lint: Ruff ✓
  - PR review: 5 agents (code-reviewer, silent-failure-hunter, pr-test-analyzer, feature-dev, superpowers) — no critical/important issues
  - Runtime: signature/`serve_all` import smoke test ✓, Quality Gates 1/2/3 모두 PASS (iter 1)

- **Unblocked**: G5 MEDIUM drift → AL 트리거 경로가 silent no-op → 실제 동작 가능으로 전환. **E-2 잔여 E2E 검증의 전제 조건이 해제**됨 — 이제 drift → AL E2E 스모크 시 unknown-kwarg 로 죽지 않고 실제 flow run 이 발화함.

- **Remaining for parent phase (E-2)** → §4 Phase E Task Board 참조:
  - Label Studio annotation webhook → `continuous-training-deployment` 런타임 발화 검증 (docker compose up 필요)
  - Drift HIGH 감지 → `continuous-training-deployment` 자동 트리거 + MLflow rollback 체인 검증
  - Drift MEDIUM 감지 → `active-learning-deployment` + `continuous-training-deployment` 병행 트리거 검증 (S5 해제로 이제 가능)

- **New follow-up**: **알려진 follow-up 티켓**: `_trigger_active_learning_pipeline()` 의 bare `except Exception:` 을 `ImportError` + `PrefectException` 으로 좁히고 실패 시 `log.ERROR` 또는 metric 승격 (silent failure concealer 제거). → §0 Resume Pointer 에 carry-over.

---

### 6-E3 · Phase E-3 베이스라인 완료 (2026-04-10)

- **Commit**: `b8c7f8a feat(alerting): Grafana multi-channel contact points + severity routing (Phase E-3)` (+ Gate 2 I1 fix `d8b12db fix(alerting): safe sentinel defaults for Grafana provisioning`)
- **PR**: (merge commit `d30b084`) feature/phase-e3-grafana-multichannel-alerting
- **Gap**: Gap 7 (Alerting/Notification)
- **Scope**: Grafana 다중 채널 알림 베이스라인. Prefect notification block 연동과 E2E 발화 검증은 후속으로 분리.

- **Changes** ([x] 는 본 블록에서 완료, [ ] 는 후속):
  - [x] **Grafana alert rules → 다중 채널 notification 설정**: `configs/grafana/alerting/contact-points.yml` 을 4종 integration(Email/Slack/Generic Webhook/PagerDuty)을 묶은 2개 contact point(`default-multi`, `critical-escalation`)로 교체. 모든 URL/키는 환경 변수 치환이라 비활성 채널은 자동 no-op.
  - [x] **Alert rule 템플릿화**: 이미 `configs/grafana/alerting/alerts.yml` 에 3개 rule 이 provisioning 으로 존재 (drift-score-warning, api-error-rate-critical, api-latency-warning). E-3 에서 severity 라벨 활용이 가능해지도록 라우팅 정책을 연결.
  - [x] **G5 HIGH severity → PagerDuty-style escalation**: `configs/grafana/alerting/notification-policies.yml` 에 `severity = critical` 매처 + `continue: true` 를 추가하여 critical 알림은 PagerDuty + 전용 Slack 메시지로 에스컬레이션되고, 동시에 기본 채널(email/slack/webhook) 에도 기록되도록 이중 경로 구성.
  - [x] **Compose 환경 변수 포워딩**: `docker-compose.yml` 의 `grafana` 서비스에 `GF_SMTP_*` (네이티브) + `GRAFANA_ALERT_EMAIL_ADDRESSES` / `GRAFANA_SLACK_WEBHOOK_URL` / `GRAFANA_GENERIC_WEBHOOK_URL` / `GRAFANA_PAGERDUTY_INTEGRATION_KEY` (provisioning 치환용) 추가. `.env.example` 에 alerting 블록 추가.
  - [ ] Quality gate failure → Prefect notification block 연동 (후속)
  - [ ] Alert firing E2E 테스트 (docker compose 환경에서 임계치 인위 하향 → 4채널 발화 확인)

- **Files changed**:
  - `configs/grafana/alerting/contact-points.yml` — `default-multi` (Email + Slack + Generic Webhook) + `critical-escalation` (PagerDuty + Slack) 2개 contact point 로 전면 교체. 모든 integration 자격 증명은 `${VAR}` 치환.
  - `configs/grafana/alerting/notification-policies.yml` — root → `default-multi`, 자식 route (`severity = critical` matcher + `continue: true`) → `critical-escalation` 로 라우팅 트리 재구성.
  - `docker-compose.yml` — `grafana` 서비스에 `GF_SMTP_*` 네이티브 설정과 `GRAFANA_ALERT_EMAIL_ADDRESSES` / `GRAFANA_SLACK_WEBHOOK_URL` / `GRAFANA_GENERIC_WEBHOOK_URL` / `GRAFANA_PAGERDUTY_INTEGRATION_KEY` 환경 변수 포워딩 추가.
  - `.env.example` — Grafana alerting 블록 신설 (SMTP/Slack/Webhook/PagerDuty 플레이스홀더).
  - `docker/orchestration/Dockerfile` — Phase E-1 의 CT 런타임 결손 보완: `cleanlab>=2.7`, `cleanvision>=0.3.6` 추가 (G1 `validate_images` 태스크가 worker 내부에서 실제 import 성공하도록).

- **설계 원칙**:
  - **Fault tolerance**: 한 채널 장애가 알림 체인 전체를 침묵시키지 않음 — 각 integration 은 독립 receiver 로 병렬 발송.
  - **Progressive enablement**: 비어 있는 env 변수는 해당 integration 만 no-op 로 만들고 나머지는 정상 동작.
  - **Critical double-path**: `continue: true` 로 critical 알림이 PagerDuty 에스컬레이션 + 기본 audit 채널 양쪽에 동시 도달.

- **Verification**:
  - YAML parse OK (`yaml.safe_load` on contact-points / notification-policies / docker-compose).
  - Alert rule severity 라벨 (`warning` / `critical`) 이 이미 `alerts.yml` 에 존재함을 확인 → 라우팅 매처가 기존 룰에 그대로 매칭.
  - Runtime 발화 테스트는 docker 데몬이 있는 환경에서 후속 검증 필요 (임계치 임시 하향 → 4채널 수신 확인).

- **Unblocked**: Quality gate failure → Prefect notification block 연동 작업이 Grafana 라우팅 구조 위에서 곧바로 개시 가능.
- **Remaining**: [ ] 항목 2건 → §4 Phase E-3 Task Board.
- **New follow-up**: docker 데몬 기동 환경에서의 Alert 4채널 E2E 발화 스모크 → §0 Resume Pointer.

---

### 6-E2-runtime · Phase E-2 런타임 E2E 완주 + silent concealer 제거 (2026-04-11)

- **Commit**: (pending this session's commits — see §0 for final SHA)
- **PR**: (worked on branch `fix/phase-e2-al-flow-trigger-source`, rebased onto main)
- **Gap**: Gap 1 (Event-Driven Automation) + §0 carry-over "silent failure concealer 제거"
- **Scope**: Phase E-2 의 3개 런타임 트리거 경로 E2E 검증 + monitoring flow / labeling webhook 의 silent concealer 4곳 좁히기. 탐색 단계에서 §0 carry-over 티켓이 지목한 `_trigger_active_learning_pipeline()` 외에 동일 패턴이 `_trigger_rollback()`, `_trigger_retraining_on_drift()`, `_maybe_trigger_retraining()` 에도 있어 한 번에 정리.

- **Problem (latent silent failures 다수)**:
  1. `_trigger_active_learning_pipeline()` 의 bare `except Exception:` — 이미 §0 에 기록된 원 티켓.
  2. `_trigger_rollback()`, `_trigger_retraining_on_drift()` 도 동일 패턴. 런타임 E2E 에서 MLflow/httpx 오류가 silent 하게 묻혔고, **진짜 더 심각한 pre-existing 버그 두 개**를 숨기고 있었음:
     - (a) `_run_async(run_deployment(...))` 래퍼 — `run_deployment` 는 Prefect 의 `@sync_compatible` 이라 sync 컨텍스트에서 이미 `FlowRun` 객체를 반환한다. `_run_async(FlowRun)` → `asyncio.run(FlowRun)` 은 `ValueError: a coroutine was expected`. 이전에는 `except Exception` 이 이 값오류까지 삼키면서 CT 트리거가 동작하는 것처럼 **보였던** 상태.
     - (b) `src/core/monitoring/metrics.py` 가 top-level 로 `prometheus_fastapi_instrumentator` 를 import 하는데 Prefect worker 이미지엔 그 패키지가 없어, worker 에서 counter 를 읽는 순간 `ModuleNotFoundError` 가 터지고 rollback/retrain 트리거 전체가 연쇄 실패했다. 기존 bare except 때문에 이것도 무증상이었음.
  3. `webhook.py::_maybe_trigger_retraining()` 의 bare `except Exception:` — **api 이미지에 `prefect` 와 `httpx` 자체가 없음**. 즉 Label Studio webhook → CT 경로는 이미지가 만들어진 이후로 **단 한 번도 실제로 deployment 를 트리거한 적이 없다**. 모든 annotation 이벤트가 조용히 ImportError 로 no-op 된 상태로 200 OK 응답. 이 발견 자체가 narrow-except 의 최고 가치 사례.

- **Changes** ([x] = 본 세션, [ ] = carry-over):
  - [x] `src/core/monitoring/orchestration_counter.py` 신설 — FastAPI 의존성 없는 별도 모듈에 `ORCHESTRATION_TRIGGER_FAILURE_COUNTER` 정의. Prefect worker 에서도 import 가능.
  - [x] `src/core/monitoring/metrics.py` 가 `orchestration_counter` 에서 re-export — `/metrics` 엔드포인트에서 여전히 노출.
  - [x] `src/core/orchestration/flows/monitoring_flow.py` 3곳 narrow:
    - `_trigger_retraining_on_drift`: `(ImportError, PrefectException)` 로 좁힘 + `_run_async` 래퍼 제거 (pre-existing ValueError 버그 동반 수정) + `_record_trigger_failure("ct_on_drift", ...)`
    - `_trigger_rollback`: `(ImportError, MlflowException, httpx.HTTPError)` 로 좁힘 + `_record_trigger_failure("rollback", ...)`
    - `_trigger_active_learning_pipeline`: `(ImportError, PrefectException)` 로 좁힘 + `_run_async` 래퍼 제거 + `_record_trigger_failure("al_on_medium_drift", ...)`
  - [x] `src/core/orchestration/flows/monitoring_flow.py::_record_trigger_failure()` 헬퍼 신설 — lazy import 로 worker 컨텍스트 보호 + `logger.warning → logger.error` 승격.
  - [x] `src/core/active_learning/labeling/webhook.py::_maybe_trigger_retraining()` narrow: `(ImportError, PrefectException, httpx.HTTPError)` + `trigger_type="ct_on_labeling"`. ImportError 는 FastAPI handler 를 500 으로 escalate 하도록 설계했으나 현재 api 이미지 구성상 ImportError 가 즉시 발생하여 early-return 경로를 탄다 — 이것이 **webhook 이 여태 한 번도 발화하지 않았다**는 사실을 노출시킨 게이트.
  - [x] `tests/unit/test_monitoring_flow.py::TestNarrowTriggerExceptions` 신설 4건: PrefectException/ImportError 포착 + ValueError 전파 pin + MlflowException 포착 (rollback).
  - [x] `tests/unit/test_labeling_webhook.py` 신설 2건: PrefectException 포착 + ValueError 전파 pin.
  - [x] `scripts/seed_drift_fixtures.py` 신설 — MinIO 에 reference + HIGH/MEDIUM current 분포를 업로드. MEDIUM 은 결정론적 class 시퀀스 + confidence 만 shift 시켜 `drift_score=0.5` 를 정확히 맞춰 G5 MEDIUM 밴드에 안착.
  - [x] **Runtime E2E Test 2 (drift HIGH) PASS**: seed MinIO HIGH fixtures → monitoring-deployment 수동 트리거 → G5 HIGH 판정 → `_trigger_rollback()` 실행 → MLflow `cv-classifier@champion` alias v2 → v1 이동 확인 → httpx 422 on `/model/reload` narrow-caught (`orchestration_trigger_failure_total{trigger_type=rollback,error_class=HTTPStatusError}` 증가) → `_trigger_retraining_on_drift()` 연속 실행 → CT flow run `silky-phoenix` 생성 + `trigger_source="drift_detected"` + Completed.
  - [x] **Runtime E2E Test 3 (drift MEDIUM) PASS**: seed MEDIUM (drift_score=0.5) → monitoring 트리거 → G5 MEDIUM → **AL run `versatile-kingfisher` (Completed, trigger_source=g5_medium_drift) + CT run `dancing-bee` (Completed, trigger_source=drift_detected) 병행 발화**. Phase E-2 S5 signature fix 덕에 AL run 이 unknown-kwarg 없이 정상 수락.
  - [x] **Runtime E2E Test 1 (Label Studio webhook → CT) Partial**: `POST /webhooks/label-studio` 200 OK 라우트 확인. narrow-catch 가 pre-existing `ModuleNotFoundError: httpx/prefect` 를 **노출** — api 이미지의 pre-existing 의존성 결손 때문에 webhook 이 역사적으로 한 번도 실제 deployment 를 트리거하지 못했다는 silent 버그 확인. 실제 end-to-end 발화는 새 follow-up 으로 분리.
  - [ ] (follow-up) `docker/serving/Dockerfile` 에 `prefect` + `httpx` 추가, Label Studio project/API key 시드, webhook E2E 완주.

- **Files changed** (prep + test):
  - 신규: `src/core/monitoring/orchestration_counter.py`, `scripts/seed_drift_fixtures.py`, `tests/unit/test_labeling_webhook.py`
  - 수정: `src/core/monitoring/metrics.py` (re-export), `src/core/orchestration/flows/monitoring_flow.py` (헬퍼 + 3 narrow 사이트 + `_run_async` 래퍼 제거), `src/core/active_learning/labeling/webhook.py` (narrow + 구조 리팩터), `tests/unit/test_monitoring_flow.py` (TestNarrowTriggerExceptions 클래스 append)

- **설계 원칙**:
  - **Fail loud, not silent**: narrow 캐치는 예상되는 infra 실패(import/Prefect/MLflow/HTTP)만 흡수하고, 코드 로직 오류(`ValueError`, `KeyError` 등)는 상위로 전파. 결과적으로 과거 bare except 가 숨겼던 3개의 진짜 버그가 즉시 드러남.
  - **Observable by default**: 실패 시 `logger.error` 승격 + Prometheus counter 증가 → PromQL alert 또는 후속 Prefect notification block 연동의 기반.
  - **Layering respect**: `orchestration_counter` 모듈을 FastAPI 의존성에서 분리 → worker 컨테이너가 serving-only 모듈을 잡아먹던 layering 위반 해소.

- **Verification**:
  - Unit: `uv run pytest tests/unit -q` → **324 passed** (316 이전 + 6 narrow regression + 2 webhook = 324). 신규 `_run_async` 제거 후에도 6/6 green.
  - Lint: `uv run ruff check src/ tests/ scripts/seed_drift_fixtures.py` → all files clean (기존 `scripts/run_evidently_demo.py` 의 pre-existing ruff 이슈는 본 세션 범위 밖).
  - Runtime: Test 2 PASS (MLflow alias v2→v1, CT flow run `silky-phoenix` Completed), Test 3 PASS (AL `versatile-kingfisher` + CT `dancing-bee` 병행 Completed + trigger_source 확인). Test 1 Partial (route 200 OK + narrow-catch가 pre-existing ImportError 노출).

- **Unblocked**:
  - Gap 1 (Event-Driven Automation) drift 경로 E2E 완주 (HIGH + MEDIUM). Partial 에서 거의 Complete 로 전환 — 잔여는 Label Studio webhook 경로의 api 이미지 의존성 결손뿐.
  - §0 carry-over 1순위 (silent failure concealer 제거) 해결.
  - 후속 E-3 Prefect notification block 연동 작업이 `orchestration_trigger_failure_total` counter 위에서 곧바로 발화 기준 정의 가능.

- **Remaining for parent phase (E-2)**:
  - [ ] (follow-up) api 이미지 Dockerfile 에 `prefect` + `httpx` 추가 → webhook → CT E2E 완주. 별도 세션 권장.

- **New follow-up tickets (carry-over to §0)**:
  - **[api 이미지 의존성 결손]** `docker/serving/Dockerfile` 에 `prefect` + `httpx` 미포함. Label Studio webhook 핸들러가 역사적으로 `ImportError` 로 silent no-op. narrow-catch 가 노출한 최대 가치 finding. 우선순위: High.
  - **[model reload endpoint 422]** `http://api:8000/model/reload` 가 422 Unprocessable Entity 를 반환. `_trigger_rollback()` 의 MLflow alias 이동은 성공하지만 serving 리로드가 막혀서 새 champion 이 실전에 반영되지 않음. 우선순위: Medium.

---

### (append next session block here)

---

## 7. 참고 자료

- [Google MLOps Level 0-2 Architecture](https://docs.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [Google Practitioners Guide to MLOps](https://services.google.com/fh/files/misc/practitioners_guide_to_mlops_whitepaper.pdf)
- [ZenML vs ClearML vs MLflow Comparison](https://www.zenml.io/blog/clearml-vs-mlflow)
- [Lightly.ai Active Learning Guide](https://www.lightly.ai/blog/active-learning-in-machine-learning)
- [MLRun vs MLflow vs ZenML Comparison](https://www.zenml.io/blog/mlrun-vs-mlflow)
- [Self-Supervised Learning with Lightly AI for Data Curation](https://www.marktechpost.com/2025/10/11/a-coding-guide-to-master-self-supervised-learning-with-lightly-ai-for-efficient-data-curation-and-active-learning/)
