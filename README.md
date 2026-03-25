# MLOps Pipeline

온프레미스 환경을 위한 범용 Computer Vision MLOps 파이프라인 템플릿.
이미지 분류, 검출, 세그멘테이션 모델의 학습부터 서빙, 모니터링까지 전체 생명주기를 관리합니다.

## 아키텍처

```
Layer 6: Monitoring    — Evidently, Prometheus, Grafana
Layer 5: Serving       — Nginx, Gunicorn, Uvicorn, FastAPI
Layer 4: Orchestration — Prefect
Layer 3: Training      — PyTorch, MLflow
Layer 2: Data Pipeline — DVC, CleanLab, CleanVision
Layer 1: Infrastructure— Docker Compose, PostgreSQL, MinIO, Redis
```

## 빠른 시작

> Phase 1(Infrastructure) 구현 후 사용할 수 있습니다.

```bash
cp .env.example .env
make up
make seed
make ps
```

## 문서

| 문서 | 설명 |
|------|------|
| [아키텍처](docs/architecture.md) | 전체 시스템 구조 및 데이터 흐름 다이어그램 |
| [설치 가이드](docs/setup-guide.md) | 사전 요구사항 및 설치/실행 방법 |
| [Layer 1: Infrastructure](docs/layer-1-infrastructure.md) | 인프라 레이어 상세 |

## 기술 스택

| 영역 | 도구 |
|------|------|
| 컨테이너 | Docker Compose |
| 딥러닝 | PyTorch |
| 데이터 버전 관리 | DVC |
| 데이터 검증 | CleanLab, CleanVision |
| 실험 트래킹 | MLflow |
| 오케스트레이션 | Prefect |
| 서빙 | FastAPI, Gunicorn, Nginx |
| 모니터링 | Evidently, Prometheus, Grafana |
| 관계형 DB | PostgreSQL |
| 오브젝트 스토리지 | MinIO |
| 인메모리 스토어 | Redis |

