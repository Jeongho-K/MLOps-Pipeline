# 설치 및 실행 가이드

## 사전 요구사항

| 도구 | 최소 버전 | 설치 확인 |
|------|----------|----------|
| Docker | 24.0+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.11+ | `python --version` |
| uv | - | `uv --version` |
| git | - | `git --version` |
| Make | - | `make --version` |
| NVIDIA Container Toolkit | - | `nvidia-smi` (GPU 사용 시) |

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/Jeongho-K/MLOps-Pipeline.git
cd MLOps-Pipeline

# 2. Python 의존성 설치
uv sync

# 3. 환경변수 설정
cp .env.example .env

# 4. 서비스 시작
make up

# 5. 초기 데이터 설정 (MinIO 버킷, MLflow 실험)
make seed

# 6. 인프라 상태 확인
make verify
```

## 서비스 접속

| 서비스 | URL | 기본 인증 |
|--------|-----|----------|
| MLflow UI | http://localhost:5000 | 없음 |
| Prefect UI | http://localhost:4200 | 없음 |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |
| API (FastAPI) | http://localhost:8000 | 없음 |
| Nginx | http://localhost | 없음 |
| Prometheus | http://localhost:9090 | 없음 |
| Pushgateway | http://localhost:9091 | 없음 |
| Grafana | http://localhost:3000 | admin / admin |

## 환경변수 설정

`.env.example` 파일을 복사하여 `.env`를 생성하고, 필요에 따라 값을 수정합니다.

상세 환경변수 목록은 `.env.example` 파일과 [Layer 1: Infrastructure](layer-1-infrastructure.md) 문서를 참조하세요.

## GPU 설정

GPU를 사용하려면 NVIDIA Container Toolkit이 설치되어 있어야 합니다.

```bash
# NVIDIA Container Toolkit 설치 확인
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.6.3-runtime-ubuntu22.04 nvidia-smi
```

GPU 서비스는 `docker-compose.override.yml`에서 설정합니다 (GPU 사용 시 활성화).

## 주요 명령어

| 명령어 | 설명 |
|--------|------|
| `make install` | 의존성 설치 (uv sync) |
| `make up` | 전체 서비스 시작 |
| `make down` | 전체 서비스 중지 |
| `make down-v` | 서비스 중지 + 볼륨 삭제 |
| `make ps` | 서비스 상태 확인 |
| `make logs SERVICE=mlflow` | 서비스 로그 확인 |
| `make seed` | MinIO 버킷 및 MLflow 실험 초기화 |
| `make train` | 기본 설정으로 학습 실행 |
| `make pipeline` | 전체 파이프라인 1회 실행 (데이터 → 검증 → 학습) |
| `make pipeline-serve` | 스케줄 파이프라인 서빙 (기본: 주 1회) |
| `make drift-check` | 드리프트 감지 수동 실행 |
| `make lint` | Ruff 린터 실행 |
| `make format` | Ruff 포매터 실행 |
| `make test` | 단위 테스트 실행 |
| `make test-integration` | 통합 테스트 실행 |
| `make test-e2e` | E2E 테스트 실행 |
| `make verify` | 인프라 상태 점검 |

## 문제 해결

- 서비스가 시작되지 않는 경우: `make logs SERVICE=<서비스명>`으로 로그를 확인하세요.
- 포트 충돌 시: `.env` 파일에서 해당 서비스의 포트를 변경하세요.
- 볼륨 초기화가 필요한 경우: `make down-v`로 볼륨을 삭제 후 다시 시작하세요.
- API 서비스가 시작되지 않을 때: MLflow에 등록된 모델이 없으면 로딩에 실패할 수 있습니다. `make logs SERVICE=api`로 로그를 확인하고, 먼저 `make train`으로 모델을 학습시키세요.
- Nginx 502 에러: API 서비스가 정상 기동되지 않았을 가능성이 높습니다. `make logs SERVICE=api`로 API 상태를 확인하고, API가 healthy 상태인지 `make ps`로 점검하세요.
- Grafana 대시보드가 비어있을 때: Prometheus 데이터 소스 연결을 확인하세요. `http://localhost:9090/targets`에서 수집 대상 상태를 점검하고, 메트릭 데이터가 충분히 쌓일 때까지 잠시 기다려 보세요.
