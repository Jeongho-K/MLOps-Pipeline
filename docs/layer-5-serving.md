# Layer 5: 서빙 (Serving)

## 개요

FastAPI 기반 추론 API 서버. MLflow Model Registry에서 모델을 로드하고, 이미지 분류 추론을 수행합니다.

## 아키텍처

```
클라이언트 → Nginx (포트 80) → Gunicorn + UvicornWorker (포트 8000) → FastAPI App
                                                                        ↓
                                                                   MLflow Registry
                                                                   (모델 로딩)
```

## 구성 요소

### FastAPI 추론 API (`src/serving/api/`)

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 앱 팩토리, lifespan 관리 |
| `routes.py` | API 엔드포인트 정의 |
| `schemas.py` | Pydantic 요청/응답 스키마 |
| `dependencies.py` | 모델 로딩, 디바이스 관리 |
| `config.py` | `ServingConfig` (Pydantic Settings, `SERVING_` prefix) |

### API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스 체크 (모델 로드 상태 포함) |
| `GET` | `/model/info` | 현재 로드된 모델 메타데이터 |
| `POST` | `/predict` | 이미지 분류 추론 (multipart upload) |
| `POST` | `/model/reload` | 무중단 모델 교체 |

### Gunicorn 설정 (`src/serving/gunicorn/config.py`)

- 워커 클래스: `uvicorn.workers.UvicornWorker`
- 기본 워커 수: `min(2*CPU+1, 4)` (GPU 메모리 경합 방지)
- `preload_app = False` (CUDA fork 안전성)
- 환경변수로 전부 조정 가능 (`GUNICORN_WORKERS`, `GUNICORN_TIMEOUT` 등)

### Nginx 리버스 프록시

- Rate limiting: IP당 10 req/s, burst 20
- 보안 헤더: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`
- 클라이언트 업로드 제한: 10MB
- 추론 타임아웃: 120초

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SERVING_MODEL_NAME` | `cv-classifier` | MLflow 등록 모델 이름 |
| `SERVING_MODEL_VERSION` | `latest` | 모델 버전 |
| `SERVING_MLFLOW_TRACKING_URI` | `http://mlflow:5000` | MLflow 서버 URI |
| `SERVING_DEVICE` | `auto` | 추론 디바이스 (`auto`/`cpu`/`cuda`/`mps`) |
| `SERVING_IMAGE_SIZE` | `224` | 입력 이미지 크기 |
| `SERVING_CLASS_NAMES` | (없음) | 쉼표 구분 클래스명 (예: `cat,dog,bird`) |
| `GUNICORN_WORKERS` | `2` | Gunicorn 워커 수 |
| `API_PORT` | `8000` | API 서버 포트 |
| `NGINX_PORT` | `80` | Nginx 포트 |

## 모델 로딩 전략

**Eager + Reload 하이브리드 패턴:**

1. **시작 시 (Eager)**: lifespan에서 MLflow Registry로부터 모델 로드
2. **실패 시**: 빈 상태로 시작 (503 반환), crash loop 방지
3. **무중단 교체**: `POST /model/reload`로 새 버전 로드

```bash
# 모델 버전 교체 예시
curl -X POST http://localhost:8000/model/reload \
  -H "Content-Type: application/json" \
  -d '{"model_name": "cv-classifier", "model_version": "2"}'
```

## 사용 예시

```bash
# 추론 요청
curl -X POST http://localhost/predict \
  -F "file=@test_image.jpg"

# 모델 정보 확인
curl http://localhost/model/info

# 헬스 체크
curl http://localhost/health
```

## Docker 서비스

- `api`: FastAPI + Gunicorn (커스텀 Dockerfile: `docker/serving/Dockerfile`)
- `nginx`: Nginx 리버스 프록시 (커스텀 Dockerfile: `docker/nginx/Dockerfile`)

## 테스트

```bash
# 단위 테스트 (MLflow 연결 불필요)
uv run pytest tests/unit/test_serving_*.py -v
```
