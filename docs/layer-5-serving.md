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

## API 엔드포인트

### GET /health

```bash
curl http://localhost/health
```

```json
{"status": "ok", "model_loaded": true}
```

### GET /model/info

```bash
curl http://localhost/model/info
```

```json
{
  "model_name": "cv-classifier",
  "model_version": "1",
  "mlflow_run_id": "a1b2c3d4e5f6...",
  "num_classes": 10,
  "device": "cpu",
  "image_size": 224
}
```

### POST /predict

```bash
curl -X POST http://localhost/predict -F "file=@image.jpg"
```

```json
{
  "predicted_class": 3,
  "class_name": "cat",
  "confidence": 0.95,
  "probabilities": [0.01, 0.01, 0.02, 0.95, 0.01]
}
```

### POST /model/reload

```bash
curl -X POST http://localhost/model/reload \
  -H "Content-Type: application/json" \
  -d '{"model_name": "cv-classifier", "model_version": "2"}'
```

```json
{
  "status": "ok",
  "message": "Reloaded model 'cv-classifier' version '2'",
  "model_info": {
    "model_name": "cv-classifier",
    "model_version": "2",
    "mlflow_run_id": "b2c3d4e5f6g7...",
    "num_classes": 10,
    "device": "cpu",
    "image_size": 224
  }
}
```

## Gunicorn 설정

- 워커 클래스: `uvicorn.workers.UvicornWorker`
- 기본 워커 수: `min(2*CPU+1, 4)` (GPU 메모리 경합 방지)
- `preload_app = False` (CUDA fork 안전성)
- 환경변수로 전부 조정 가능 (`GUNICORN_WORKERS`, `GUNICORN_TIMEOUT` 등)

## Nginx 리버스 프록시

- Rate limiting: IP당 10 req/s, burst 20
- 보안 헤더: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`
- 클라이언트 업로드 제한: 10MB
- 추론 타임아웃: 120초

## 모델 로딩 전략

**Eager + Reload 하이브리드 패턴:**

1. **시작 시 (Eager)**: lifespan에서 MLflow Registry로부터 모델 로드
2. **실패 시**: 빈 상태로 시작 (503 반환), crash loop 방지
3. **무중단 교체**: `POST /model/reload`로 새 버전 로드
4. **Cross-device 호환**: `map_location="cpu"`로 MPS/CUDA 학습 모델을 CPU 컨테이너에서 로드
5. **Traceability**: `MlflowClient`로 source `run_id`를 조회하여 예측과 학습을 연결

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

## Docker 서비스

- `api`: FastAPI + Gunicorn (커스텀 Dockerfile: `docker/serving/Dockerfile`)
- `nginx`: Nginx 리버스 프록시 (커스텀 Dockerfile: `docker/nginx/Dockerfile`)

## 테스트

```bash
# 단위 테스트 (MLflow 연결 불필요)
uv run pytest tests/unit/test_serving_*.py -v
```

## 개선 방향

### Gunicorn 다중 워커 reload 상태 불일치

`preload_app = False`로 각 워커가 독립적으로 모델을 로드한다 (CUDA fork safety).
`/model/reload` 요청은 해당 워커에만 적용된다.

- 단기: `GUNICORN_WORKERS=1`로 설정하여 불일치 방지
- 장기: Redis pub/sub 등으로 워커 간 reload 시그널 전파
