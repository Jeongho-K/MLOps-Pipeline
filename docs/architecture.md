# 아키텍처

## 전체 시스템 구조

```mermaid
graph TB
    subgraph "Layer 6: Monitoring"
        Evidently[Evidently<br/>드리프트 감지]
        Prometheus[Prometheus<br/>메트릭 수집]
        Grafana[Grafana<br/>대시보드/알림]
    end

    subgraph "Layer 5: Serving"
        Nginx[Nginx<br/>리버스 프록시]
        Gunicorn[Gunicorn<br/>프로세스 관리]
        Uvicorn[Uvicorn<br/>ASGI 서버]
        FastAPI[FastAPI<br/>추론 API]
    end

    subgraph "Layer 4: Orchestration"
        Prefect[Prefect<br/>워크플로우 스케줄링]
    end

    subgraph "Layer 3: Training"
        PyTorch[PyTorch<br/>모델 학습]
        MLflow[MLflow<br/>실험 트래킹/모델 레지스트리]
    end

    subgraph "Layer 2: Data Pipeline"
        DVC[DVC<br/>데이터 버전 관리]
        CleanLab[CleanLab/CleanVision<br/>데이터 검증]
    end

    subgraph "Layer 1: Infrastructure"
        PostgreSQL[(PostgreSQL<br/>메타데이터 DB)]
        MinIO[(MinIO<br/>S3 오브젝트 스토리지)]
        Redis[(Redis<br/>메시징)]
        Docker[Docker Compose<br/>컨테이너 오케스트레이션]
    end

    Nginx --> Gunicorn --> Uvicorn --> FastAPI
    Prefect --> PyTorch
    Prefect --> DVC
    Prefect --> CleanLab
    PyTorch --> MLflow
    MLflow --> PostgreSQL
    MLflow --> MinIO
    DVC --> MinIO
    Prefect --> PostgreSQL
    Prefect --> Redis
    Prometheus -->|스크래핑| Evidently
    Grafana -->|쿼리| Prometheus
    FastAPI --> MLflow
```

## 레이어 의존성

```mermaid
graph LR
    L1[Layer 1<br/>Infrastructure] --> L2[Layer 2<br/>Data Pipeline]
    L1 --> L3[Layer 3<br/>Training]
    L2 --> L3
    L1 --> L4[Layer 4<br/>Orchestration]
    L2 --> L4
    L3 --> L4
    L1 --> L5[Layer 5<br/>Serving]
    L3 --> L5
    L1 --> L6[Layer 6<br/>Monitoring]
    L5 --> L6
```

**규칙:** 상위 레이어는 하위 레이어만 참조 가능. 역방향 의존성 금지.

> Layer 5(Serving)는 Layer 4(Orchestration)에 의존하지 않습니다. 모델 배포는 MLflow 모델 레지스트리를 통해 트리거됩니다.

## 서비스 포트 맵

| 서비스 | 포트 | 용도 |
|--------|------|------|
| PostgreSQL | 5432 | 메타데이터 DB |
| MinIO API | 9000 | S3 호환 API |
| MinIO Console | 9001 | 웹 관리 UI |
| MLflow | 5000 | 실험 트래킹 UI + API |
| Prefect | 4200 | 오케스트레이션 UI + API |
| Redis | 6379 | Prefect 메시징 |
| FastAPI | 8000 | 추론 API (Phase 5) |
| Nginx | 80 | 리버스 프록시 (Phase 5) |
| Prometheus | 9090 | 메트릭 수집 (Phase 6) |
| Grafana | 3000 | 대시보드 (Phase 6) |

## 데이터 흐름

```mermaid
graph LR
    A[원본 데이터] -->|DVC| B[버전 관리된 데이터셋]
    B -->|CleanLab| C[검증된 데이터셋]
    C -->|PyTorch| D[학습된 모델]
    D -->|MLflow| E[모델 레지스트리]
    E -->|FastAPI| F[추론 서비스]
    F -->|Evidently| G[드리프트 감지]
    G -->|Prometheus| H[메트릭 저장]
    H -->|Grafana| I[대시보드/알림]
```

## 구현 로드맵

| Phase | 레이어 | 핵심 구현 |
|-------|--------|----------|
| 0 | 프로젝트 기반 | CLAUDE.md, docs, Makefile, pyproject.toml |
| 1 | Infrastructure | Docker Compose, PostgreSQL, MinIO, MLflow Server, Prefect Server, Redis |
| 2 | Data Pipeline | DVC (MinIO 리모트), CleanLab/CleanVision, 데모 데이터셋 |
| 3 | Training | PyTorch 이미지 분류, MLflow 실험 트래킹, 모델 레지스트리 |
| 4 | Orchestration | Prefect 워크플로우, 스케줄링, 에러 핸들링 |
| 5 | Serving | FastAPI, Gunicorn/Uvicorn, Nginx, 모델 버전 라우팅 |
| 6 | Monitoring | Evidently 드리프트, Prometheus 메트릭, Grafana 대시보드 |
