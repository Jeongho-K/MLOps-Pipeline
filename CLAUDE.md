# Active Learning-First MLOps Platform

## Core Philosophy

> **이 프로젝트는 Active Learning Loop을 중심으로 모든 MLOps 컴포넌트가 유기적으로 연결된 폐루프(closed-loop) ML 운영 플랫폼이다.**

Production-grade on-premises MLOps platform. CV first, domain-agnostic by design.

### 5 Core Principles

1. **Closed-Loop by Design** — 파이프라인은 순환형이다: train → serve → monitor → select → label → retrain. 모니터링이 끝이 아니라 다음 학습의 시작점.
2. **Dual-Path Data Flywheel** — 서빙되는 모든 데이터는 학습 자산이다. High confidence → pseudo-label 자동 축적. Low confidence → human labeling queue. 서비스 운영이 곧 모델 개선.
3. **Event-Driven Automation** — 시간 기반이 아닌 사건 기반(drift 감지, 라벨링 완료, 품질 임계치 위반)으로 파이프라인 작동. 필요할 때만 자원 사용, 필요할 때 즉시 반응.
4. **Domain-Agnostic Core + Plugins** — Active Learning Loop의 흐름은 도메인 무관. CV, NLP, Tabular는 Plugin으로 존재. Framework가 흐름을, Plugin이 구현을 담당.
5. **Quality Gate at Every Transition** — 모든 상태 전환에 자동화된 품질 검증. Gate 없는 자동화는 사고다.

### Data Flywheel

```
Serve → Monitor → Confidence Split
                    ├─ High conf → Auto-Accumulate (pseudo-label) ─┐
                    └─ Low conf  → Label Studio (human review)  ───┤
                                                                    ▼
                                                              Retrain (Prefect)
                                                                    │
                                                           Evaluate (Champion Gate)
                                                                    │
                                                             Deploy (Canary)
                                                                    │
                                                                  Serve ← (loop)
```

### Four Pillars (Functional Architecture)

| Pillar | Role | Key Components |
|---|---|---|
| **Active Learning Engine** (심장) | 어떤 데이터를 학습할지 결정 | Uncertainty Estimator, Confidence Router, Sample Selector, Auto-Accumulator, Label Studio Bridge |
| **Monitoring & Trigger** (눈과 귀) | 시스템 감시 + 이벤트 발생 | Prometheus, Evidently, Confidence Tracker, Alert & Trigger |
| **CI/CD Pipeline** (품질 보증) | 코드와 모델의 품질 보증 | GitHub Actions, CML, DVC, Quality Gates |
| **Orchestration** (접착제) | Event-driven flow 연결 | Prefect flows: training, monitoring, active_learning, deployment, data_accumulation |

### Quality Gates (5-Gate System)

| Gate | Location | Validates | On Failure |
|---|---|---|---|
| G1: Data Quality | Before train | health score, pseudo-label ratio, min size | Block training |
| G2: Training Quality | After train | val metrics, overfitting check | Block registration |
| G3: Champion Gate | Before deploy | New model vs champion comparison | Block deployment |
| G4: Canary Gate | After canary | error rate, latency, confidence | Auto-rollback |
| G5: Runtime Gate | During serving | drift, confidence anomaly, error spike | Trigger AL or rollback |

### Implementation Phases

| Phase | Focus | Status |
|---|---|---|
| A: Active Learning Core | Uncertainty, routing, Label Studio, pseudo-labels | **Implemented** |
| B: Continuous Training Loop | Event-driven retrain, champion gate, data integration | **Implemented** |
| C: CI/CD & Deployment | GitHub Actions, CML, canary deploy, rollback | **Implemented** |
| D: Architecture Refactoring | core/ + plugins/ restructure, Protocol interfaces | Planned |

Design spec: `docs/specs/2026-03-29-active-learning-first-mlops-design.md`

## Architecture

### Infrastructure Layers (6-Layer)

인프라 관점의 계층 분리. 상위 레이어는 하위 레이어만 참조 가능.

```
Layer 6: Monitoring    — Evidently, Prometheus, Grafana
Layer 5: Serving       — Nginx, Gunicorn, Uvicorn, FastAPI
Layer 4: Orchestration — Prefect
Layer 3: Training      — PyTorch, MLflow
Layer 2: Data Pipeline — DVC, CleanLab, CleanVision
Layer 1: Infrastructure— Docker Compose, PostgreSQL, MinIO, Redis
```

**Layer dependency rule:** Upper layers may only reference lower layers. Never import upward.

### Functional Pillars (4-Pillar) — See "Core Philosophy" section above

6-Layer(인프라 뷰)와 4-Pillar(기능 뷰)는 보완 관계. 개발 시 양쪽 모두 준수.

## Tech Stack

Versions are pinned in `docker-compose.yml` (infra) and `pyproject.toml` (Python deps). Python 3.11.x.

## Coding Standards

- **Python**: 3.11+, type hints required on all function signatures
- **Package manager**: uv (`uv sync`, `uv run`)
- **Linter/Formatter**: Ruff (config in `pyproject.toml`)
- **Config management**: Pydantic Settings (`.env` → typed dataclass)
- **Docstrings**: Google style, in English
- **Logging**: `logging` module only, never `print()`
- **No hardcoded credentials**: All secrets via environment variables

## Docker Rules

- Pin base image versions — never use `:latest`
- Multi-stage builds for all custom images
- Prefer official Docker images when available
- GPU support: `deploy.resources.reservations.devices` in compose
- Each service has its own Dockerfile in `docker/`

## Language Rules

- **Code** (variables, functions, classes, comments, docstrings): English
- **Documentation** (`docs/*.md`, `README.md`): Korean
- **Commit messages**: English, conventional commits (`feat:`, `fix:`, `docs:`, `infra:`, `test:`, `refactor:`)
- **Branches**: `feature/{description}`, `fix/{description}`


## Testing

- **Runner**: pytest
- **Unit tests**: `tests/unit/` — no external dependencies
- **Integration tests**: `tests/integration/` — requires running Docker services
- **E2E tests**: `tests/e2e/` — full pipeline tests
- **Naming**: `test_<module>_<behavior>.py`

## MCP 도구 활용

**추측하지 말고 MCP 도구로 확인한다.** 사용 가능한 MCP 도구가 있으면 적극 활용할 것:
- **Context7**: 라이브러리/프레임워크 공식 문서 조회 (API, 설정, 마이그레이션 등)
- **Tavily**: 웹 검색, 최신 정보 확인, 에러 해결책 탐색
- **Hugging Face**: 모델, 데이터셋, 논문 검색
- **기타 MCP 도구**: 사용 가능한 도구가 있으면 상황에 맞게 활용

원칙: 확실하지 않으면 MCP 도구로 먼저 확인하고 작업한다.

## Documentation

- Architecture diagrams: Mermaid syntax
- README.md: lightweight (intro + quickstart + docs links only)
- Detailed docs in `docs/` directory, one file per layer
- Update relevant docs when changing configuration

## Directory Structure

### Current (pre-Phase D refactoring)

```
data-flywheel/
├── CLAUDE.md                 # This file — project philosophy + rules
├── README.md                 # Project intro + docs links (Korean)
├── docker-compose.yml        # All services
├── docker-compose.override.yml # GPU/dev overrides
├── .env.example              # Environment variable template
├── Makefile                  # Common commands
├── pyproject.toml            # Python tooling config
├── docker/                   # Dockerfiles per service
├── src/                      # Source code (by layer)
│   ├── data/                 # Layer 2: validation, preprocessing
│   ├── training/             # Layer 3: models, trainers, configs
│   ├── serving/              # Layer 5: FastAPI, nginx, gunicorn
│   ├── orchestration/        # Layer 4: Prefect flows, tasks
│   ├── monitoring/           # Layer 6: Evidently, Prometheus, Grafana
│   ├── active_learning/      # Pillar 1: AL Engine (uncertainty, routing, accumulation, labeling)
│   └── common/               # Shared utilities
├── configs/                  # Service configuration files
├── tests/                    # unit, integration, e2e
├── scripts/                  # Setup and utility scripts
├── examples/                 # Example templates
└── docs/                     # Documentation (Korean)
```

Phase D target structure is documented in `docs/specs/2026-03-29-active-learning-first-mlops-design.md`.