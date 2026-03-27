# MLOps Pipeline - Project Rules

## Overview

General-purpose CV MLOps pipeline template for on-premises deployment.
Supports image classification, detection, and segmentation workflows.

## Quick Start

```bash
uv sync                       # Install Python dependencies
cp .env.example .env          # Configure environment (adjust ports if needed)
make up                       # Start all services
make seed                     # Initialize buckets + MLflow experiment
make verify                   # 13-point health check
```

Services after `make up`:
- MLflow UI: http://localhost:5000 (or `$MLFLOW_PORT`)
- Prefect UI: http://localhost:4200
- MinIO Console: http://localhost:9001 (minioadmin / minioadmin123)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin / admin)
- Pushgateway: http://localhost:9091

## Architecture (6 Layers)

```
Layer 6: Monitoring    — Evidently, Prometheus, Grafana
Layer 5: Serving       — Nginx, Gunicorn, Uvicorn, FastAPI
Layer 4: Orchestration — Prefect
Layer 3: Training      — PyTorch, MLflow
Layer 2: Data Pipeline — DVC, CleanLab, CleanVision
Layer 1: Infrastructure— Docker Compose, PostgreSQL, MinIO, Redis
```

**Layer dependency rule:** Upper layers may only reference lower layers. Never import upward.

## Tech Stack (Pinned Versions)

| Component | Version / Image | Notes |
|---|---|---|
| PostgreSQL | `postgres:16.6-alpine` | |
| MinIO Server | `minio/minio:RELEASE.2025-09-07T16-13-09Z` | |
| MinIO Client | `minio/mc:RELEASE.2025-08-13T08-35-41Z` | Bucket init only |
| MLflow | `docker/mlflow/Dockerfile` (base: `ghcr.io/mlflow/mlflow:v3.10.1`) | Custom build: +psycopg2-binary +boto3 |
| Prefect | `prefecthq/prefect:3.6.23-python3.11` | Requires explicit `command` |
| Redis | `redis:7.4-alpine` | |
| Nginx | `nginx:1.28.1-alpine` | Phase 5 |
| FastAPI | `fastapi>=0.115` + `uvicorn>=0.30` + `gunicorn>=22.0` | Phase 5 |
| Prometheus | `prom/prometheus:v3.10.0` | Phase 6 |
| Pushgateway | `prom/pushgateway:v1.11.0` | Phase 6 |
| Grafana | `grafana/grafana-oss:12.4.1` | Phase 6 |
| Python | 3.11.x | |
| PyTorch | 2.6.x | Phase 3 |
| CUDA | `nvidia/cuda:12.6.3-runtime-ubuntu22.04` | Phase 3 |

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
- **Branches**: `feature/phase-{N}-{name}`, `fix/{description}`


## Testing

- **Runner**: pytest
- **Unit tests**: `tests/unit/` — no external dependencies
- **Integration tests**: `tests/integration/` — requires running Docker services
- **E2E tests**: `tests/e2e/` — full pipeline tests
- **Naming**: `test_<module>_<behavior>.py`

## MCP 도구 활용

개발 중 추측하지 말고 MCP 도구로 확인한다:
- **Context7**: 라이브러리 API, 설정 방법, Docker 이미지 사용법 등 공식 문서 조회
- **Tavily**: Docker Hub 태그 존재 여부, 최신 버전, 호환성 등 웹 검색
- **Hugging Face**: 모델, 데이터셋 검색 (Phase 2~3)

활용 시점:
- Docker 이미지 태그를 지정할 때 → Tavily로 실제 존재 여부 확인
- 프레임워크 설정이 불확실할 때 → Context7으로 공식 문서 조회
- 에러 발생 시 → Tavily/Context7으로 해결책 검색

## Documentation

- Architecture diagrams: Mermaid syntax
- README.md: lightweight (intro + quickstart + docs links only)
- Detailed docs in `docs/` directory, one file per layer
- Update relevant docs when changing configuration

## Directory Structure

```
MLOps-Pipeline/
├── CLAUDE.md                 # This file
├── README.md                 # Project intro + docs links (Korean)
├── docker-compose.yml        # All services
├── docker-compose.override.yml # GPU/dev overrides
├── .env.example              # Environment variable template
├── Makefile                  # Common commands
├── pyproject.toml            # Python tooling config
├── docker/                   # Dockerfiles per service
├── src/                      # Source code (by layer)
│   ├── data/                 # Layer 2: DVC, validation, preprocessing
│   ├── training/             # Layer 3: models, trainers, configs
│   ├── serving/              # Layer 5: FastAPI, nginx, gunicorn
│   ├── orchestration/        # Layer 4: Prefect flows, tasks
│   └── monitoring/           # Layer 6: Evidently, Prometheus, Grafana
├── configs/                  # Service configuration files
├── tests/                    # unit, integration, e2e
├── scripts/                  # Setup and utility scripts
├── examples/                 # Example templates
└── docs/                     # Documentation (Korean)
```

## Make Commands

| Command | Description |
|---|---|
| `make install` | Install dependencies (uv sync) |
| `make up` | Start all services |
| `make down` | Stop all services |
| `make down-v` | Stop and destroy volumes |
| `make ps` | Show service status |
| `make logs SERVICE=mlflow` | Tail service logs |
| `make seed` | Initialize MinIO buckets and MLflow experiments |
| `make train` | Run training with default config |
| `make pipeline` | Run full pipeline once (data → validate → train) |
| `make pipeline-serve` | Serve pipeline with schedule (default: weekly) |
| `make lint` | Run Ruff linter |
| `make format` | Run Ruff formatter |
| `make test` | Run unit tests |
| `make test-integration` | Run integration tests |
| `make test-e2e` | Run end-to-end tests |
| `make verify` | Run Phase verification checks |
| `make drift-check` | Run drift detection manually |

## Gotchas

- **Port 5000 충돌**: macOS ControlCenter가 5000 사용. `.env`에서 `MLFLOW_PORT=5050`으로 변경
- **MLflow + PostgreSQL**: 공식 MLflow 이미지에 `psycopg2` 미포함 → `docker/mlflow/Dockerfile`로 커스텀 빌드 필수
- **Prefect 서버 시작**: 이미지 기본 entrypoint가 서버를 시작하지 않음 → `command: prefect server start --host 0.0.0.0 --port 4200` 필수
- **MinIO mc 이미지**: `minio/minio` 서버 이미지에 `mc` CLI 미포함. 버킷 작업은 별도 `minio/mc` 이미지 사용
- **DB 초기화 스크립트**: `scripts/create-multiple-databases.sh`는 볼륨이 비어있을 때만 실행. DB 추가 시 `make down-v` 필요
- **학습 시 S3 인증**: 로컬에서 `make train` 실행 시 MinIO 인증 환경변수 필요:
  `MLFLOW_S3_ENDPOINT_URL=http://localhost:9000 AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin123`
- **MLflow DNS Rebinding 방어**: MLflow 3.x는 Host 헤더 검증으로 DNS rebinding 공격 차단. Docker 내부 호스트명(`mlflow:5000`) 사용 시 `MLFLOW_SERVER_ALLOWED_HOSTS` 환경변수 필요
- **`/model/reload` 멀티워커 제약**: Gunicorn 워커 N개 중 reload 요청을 받은 워커에만 적용. 전체 워커에 적용하려면 컨테이너 재시작 또는 `GUNICORN_WORKERS=1` 설정
