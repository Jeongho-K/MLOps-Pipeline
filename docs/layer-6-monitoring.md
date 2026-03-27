# Layer 6: 모니터링 (Evidently + Prometheus + Grafana)

## 개요

Layer 6은 서빙 API의 실시간 메트릭 수집과 예측 데이터의 드리프트 감지를 담당한다.

```
FastAPI (/predict)
  ├─→ Prometheus 메트릭 (인프로세스)
  │     └─→ Prometheus 서버 (15초 스크랩)
  │           └─→ Grafana 대시보드
  └─→ 예측 로거 (JSONL → MinIO)
        └─→ Prefect 스케줄 플로우 (일간)
              └─→ Evidently 드리프트 리포트
                    ├─→ Prometheus Pushgateway
                    └─→ HTML 리포트 → MinIO
```

## 구성요소

### 1. Prometheus 메트릭 (실시간)

**파일:** `src/monitoring/metrics.py`

`prometheus-fastapi-instrumentator`를 통해 HTTP 메트릭을 자동 수집하고, 커스텀 메트릭을 추가한다.

**자동 수집 메트릭:**
- `http_requests_total` — 요청 수 (method, handler, status 라벨)
- `http_request_duration_seconds` — 응답 시간 히스토그램

**커스텀 메트릭:**
- `prediction_class_total` — 클래스별 예측 수 (`predicted_class` 라벨)
- `prediction_confidence` — 예측 신뢰도 분포 히스토그램

**엔드포인트:** `GET /metrics` (Prometheus 포맷)

### 2. 예측 로거 (배치 분석용)

**파일:** `src/monitoring/prediction_logger.py`

매 `/predict` 요청마다 예측 결과를 버퍼링하고 MinIO에 JSONL로 저장한다.

**저장 경로:** `s3://prediction-logs/{YYYY-MM-DD}/{uuid}.jsonl`

**레코드 형식:**
```json
{
  "timestamp": "2026-03-26T12:00:00+00:00",
  "predicted_class": 2,
  "class_name": "bird",
  "confidence": 0.95,
  "probabilities": [0.02, 0.03, 0.95]
}
```

**특성:**
- 스레드 세이프 버퍼 (threading.Lock)
- 임계값(기본 50건) 초과 시 자동 플러시
- S3 업로드 실패 시 재시도를 위해 버퍼에 재삽입
- 서버 종료 시 잔여 로그 플러시

### 3. Evidently 드리프트 감지 (배치)

**파일:**
- `src/monitoring/evidently/config.py` — `DriftConfig` (DRIFT_ 프리픽스)
- `src/monitoring/evidently/drift_detector.py` — 드리프트 분석 로직

**워크플로우:**
1. 참조 데이터셋(baseline)과 최근 예측 로그를 비교
2. `DataDriftPreset`으로 통계적 드리프트 테스트 실행
3. 드리프트 스코어와 상태를 Prometheus Pushgateway에 push
4. HTML 리포트를 MinIO에 저장

**Pushgateway 메트릭:**
- `evidently_drift_detected` — 드리프트 감지 여부 (0 또는 1)
- `evidently_drift_score` — 드리프트된 컬럼 비율 (0.0~1.0)

### 4. Prefect 모니터링 플로우

**파일:** `src/orchestration/flows/monitoring_flow.py`

일간 스케줄로 실행되는 드리프트 모니터링 파이프라인.

**태스크:**
1. `fetch_prediction_logs` — MinIO에서 최근 N일 예측 로그 수집
2. `fetch_reference_data` — 참조 데이터셋 로드
3. `run_drift_detection` — Evidently 분석 + Pushgateway push
4. `upload_drift_report` — HTML 리포트를 MinIO에 업로드

**수동 실행:** `make drift-check`

### 5. Grafana 대시보드

**파일:** `configs/grafana/dashboards/mlops-overview.json`

단일 통합 대시보드로 3개 행(Row)으로 구성:

| 행 | 패널 | 데이터 소스 |
|---|---|---|
| Row 1: 서빙 | Request Rate, Latency p50/p95/p99, Error Rate (5xx) | Prometheus (api) |
| Row 2: 예측 | Class Distribution, Confidence Histogram | Prometheus (api) |
| Row 3: 드리프트 | Drift Score Timeline, Drift Status | Prometheus (pushgateway) |

**접속:** http://localhost:3000 (admin / admin)

## Docker 서비스

| 서비스 | 이미지 | 포트 | 역할 |
|---|---|---|---|
| prometheus | `prom/prometheus:v3.10.0` | 9090 | 메트릭 수집 + 저장 |
| pushgateway | `prom/pushgateway:v1.11.0` | 9091 | 배치 메트릭 수신 |
| grafana | `grafana/grafana-oss:12.4.1` | 3000 | 시각화 |

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PROMETHEUS_PORT` | 9090 | Prometheus 포트 |
| `PUSHGATEWAY_PORT` | 9091 | Pushgateway 포트 |
| `GRAFANA_PORT` | 3000 | Grafana 포트 |
| `GRAFANA_ADMIN_USER` | admin | Grafana 관리자 ID |
| `GRAFANA_ADMIN_PASSWORD` | admin | Grafana 관리자 비밀번호 |
| `DRIFT_S3_ENDPOINT` | http://minio:9000 | MinIO 엔드포인트 |
| `DRIFT_LOOKBACK_DAYS` | 1 | 분석 대상 일수 |
| `DRIFT_PUSHGATEWAY_URL` | http://pushgateway:9091 | Pushgateway URL |

## 트러블슈팅

### Prometheus가 API 메트릭을 수집하지 않음
- `http://localhost:9090/targets`에서 `api` 타겟 상태 확인
- API 서비스가 healthy 상태인지 확인: `docker compose ps api`
- 직접 메트릭 확인: `curl http://localhost:8000/metrics`

### Grafana 대시보드가 비어있음
- Prometheus 데이터소스 연결 확인: Grafana > Configuration > Data Sources
- 대시보드 프로비저닝 확인: `docker compose logs grafana | grep dashboard`

### 드리프트 감지 실패
- 참조 데이터 존재 여부: `mc ls myminio/prediction-logs/reference/baseline.jsonl`
- 예측 로그 존재 여부: `mc ls myminio/prediction-logs/$(date +%Y-%m-%d)/`
- Pushgateway 상태: `curl http://localhost:9091/metrics`

### MinIO 버킷 미생성
- `make down-v && make up && make seed` 로 전체 초기화
- 또는 수동 생성: `mc mb myminio/prediction-logs && mc mb myminio/drift-reports`
