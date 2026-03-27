# 개선 사항

Phase 1-6 완료 후 QC 과정에서 도출된 개선 포인트.
각 항목은 코드베이스를 검증한 후 공식 문서를 참조하여 작성되었습니다.

---

## 서빙 (Layer 5)

### 1. Gunicorn — 다중 워커 환경에서 `/model/reload` 상태 불일치

**현재 상태**
`src/serving/gunicorn/config.py`에서 `preload_app = False`로 설정되어 있으며,
CUDA fork safety를 위한 의도적 결정으로 주석에 명시되어 있다.
이로 인해 각 워커가 독립적으로 모델을 로드하며, `/model/reload` 요청은 해당 워커에만 적용된다.

**개선 방향**
단기: `GUNICORN_WORKERS=1`로 설정하여 불일치를 방지한다 (CLAUDE.md Gotchas에 이미 기록됨).
장기: Redis pub/sub 등으로 워커 간 reload 시그널을 전파하는 메커니즘을 구현한다.

**우선순위**: 중간

---

## 모니터링 (Layer 6)

### 2. Prometheus — 데이터 보존 기간 미설정

**현재 상태**
`docker-compose.yml`의 Prometheus 서비스에 `command:` 필드가 없어 기본값 15일이 적용된다.

**개선 방향**
Prometheus 서비스에 retention 플래그를 추가한다.
디스크 할당량의 80-85% 이하로 크기 기반 보존을 함께 설정한다.

```yaml
# docker-compose.yml — prometheus 서비스
prometheus:
  image: prom/prometheus:v3.10.0
  command:
    - "--config.file=/etc/prometheus/prometheus.yml"
    - "--storage.tsdb.path=/prometheus"
    - "--storage.tsdb.retention.time=30d"
    - "--storage.tsdb.retention.size=8GB"
    - "--storage.tsdb.wal-compression=true"
```

**우선순위**: 중간

---

### 3. Grafana — Alerting 미구성 (드리프트 임계값 알림 부재)

**현재 상태**
`evidently_drift_detected` 및 `evidently_drift_score` 메트릭이 Prometheus에 push되지만,
Grafana에서 Alert Rule과 알림 채널(Contact Point)이 구성되어 있지 않다.

**개선 방향**
`configs/grafana/provisioning/alerting/` 아래에 프로비저닝 파일을 추가한다.

```yaml
# configs/grafana/provisioning/alerting/drift_alerts.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: mlops-slack
    receivers:
      - uid: slack-receiver
        type: slack
        settings:
          url: ${SLACK_WEBHOOK_URL}
          recipient: "#mlops-alerts"

groups:
  - orgId: 1
    name: drift-alerts
    folder: MLOps
    interval: 5m
    rules:
      - uid: drift-detected-rule
        title: "Data Drift Detected"
        condition: C
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: evidently_drift_detected
          - refId: C
            datasourceUid: "__expr__"
            model:
              type: threshold
              conditions:
                - evaluator:
                    params: [1]
                    type: gt
        for: 5m
        annotations:
          summary: "모델 입력 데이터 드리프트 감지됨"
```

**우선순위**: 높음

---

### 4. Evidently — 드리프트 감지 자동 스케줄링 미연동

**현재 상태**
`src/orchestration/flows/monitoring_flow.py`에 `monitoring_pipeline` Prefect flow가 구현되어 있으나,
스케줄 기반 자동 실행이 설정되어 있지 않다. 현재는 `make drift-check`로 수동 실행만 가능하다.

**개선 방향**
기존 `monitoring_pipeline` flow를 Prefect deployment로 등록하여 주기적으로 실행한다.
`src/orchestration/serve.py` 패턴을 참고하여 monitoring serve 엔트리포인트를 추가한다.

```python
# src/orchestration/serve.py에 monitoring deployment 추가
from src.orchestration.flows.monitoring_flow import monitoring_pipeline

monitoring_pipeline.serve(
    name="drift-monitoring",
    cron="0 2 * * *",  # 매일 새벽 2시
)
```

또는 Makefile에 별도 타겟을 추가한다:

```makefile
drift-serve:
	uv run python -c "from src.orchestration.flows.monitoring_flow import monitoring_pipeline; monitoring_pipeline.serve(name='drift-monitoring', cron='0 2 * * *')"
```

**우선순위**: 높음

---

## 테스트

### 5. E2E 테스트 미작성

**현재 상태**
`tests/e2e/.gitkeep`만 존재하며 E2E 테스트가 없다.

**개선 방향**
최소한 다음 시나리오를 포함하는 E2E 테스트를 작성한다:
1. 학습 flow 실행 → MLflow 모델 등록 확인
2. 서빙 API → `/predict` 이미지 추론 확인
3. Pushgateway → Prometheus 메트릭 전파 확인

```python
# tests/e2e/test_full_pipeline.py
import httpx
import pytest

@pytest.mark.e2e
def test_predict_endpoint_responds():
    """서빙 API가 이미지 추론 요청에 정상 응답하는지 확인한다."""
    with open("tests/fixtures/sample.jpg", "rb") as f:
        response = httpx.post(
            "http://localhost:80/predict",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            timeout=30,
        )
    assert response.status_code == 200
    payload = response.json()
    assert "predicted_class" in payload
    assert 0.0 <= payload["confidence"] <= 1.0
```

**우선순위**: 중간

---

### 6. 부하 테스트 미작성 (Locust)

**현재 상태**
서빙 API의 처리 용량과 레이턴시 특성을 측정하는 부하 테스트가 없다.

**개선 방향**
Locust를 사용해 `/predict` 엔드포인트에 대한 부하 테스트를 작성한다.

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class InferenceUser(HttpUser):
    """MLOps Pipeline 서빙 API 부하 테스트 사용자."""

    host = "http://localhost:80"  # Nginx 프록시 경유
    wait_time = between(0.05, 0.2)

    @task(10)
    def predict(self) -> None:
        with open("tests/fixtures/sample.jpg", "rb") as f:
            self.client.post(
                "/predict",
                files={"file": ("sample.jpg", f, "image/jpeg")},
                name="/predict",
            )

    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")
```

실행:
```bash
uv run locust -f tests/load/locustfile.py --headless \
    --users 50 --spawn-rate 5 --run-time 60s
```

**우선순위**: 중간

---

## 인프라 (Layer 1)

### 7. Postgres healthcheck — `start_period` 미설정

**현재 상태**
`docker-compose.yml`에 PostgreSQL healthcheck이 설정되어 있고,
MLflow/Prefect 모두 `condition: service_healthy`를 사용하고 있다.
단, `start_period`가 설정되어 있지 않아 초기화 중 불필요한 healthcheck 실패가 발생할 수 있다.

**개선 방향**
healthcheck에 `start_period: 30s`를 추가하여 초기화 기간 동안 실패를 무시한다.

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-mlops}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s  # 추가
```

**우선순위**: 낮음

---

### 8. MinIO — 버킷 버전 관리(Versioning) 미활성화

**현재 상태**
모델 아티팩트와 데이터셋이 MinIO에 저장되지만 버킷 버전 관리가 활성화되어 있지 않다.

**개선 방향**
`minio-init` 서비스 또는 `scripts/seed_data.sh`에서 버전 관리를 활성화한다:

```bash
mc version enable myminio/mlflow-artifacts
mc version enable myminio/model-registry
```

**우선순위**: 낮음

---

## CI/CD

### 9. GitHub Actions CI 파이프라인 미구성

**현재 상태**
`.github/workflows/` 디렉터리가 없어 PR 생성 시 자동 lint/테스트가 실행되지 않는다.

**개선 방향**
Ruff + pytest + Docker build 3단계 워크플로우를 추가한다.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv sync

      - name: Lint
        run: uv run ruff check --output-format=github .

      - name: Format check
        run: uv run ruff format --diff .

      - name: Unit tests
        run: uv run pytest tests/unit/ -v

  docker-build:
    runs-on: ubuntu-latest
    needs: lint-and-test
    steps:
      - uses: actions/checkout@v5

      - name: Build MLflow image
        run: docker build -t mlops/mlflow:ci docker/mlflow/

      - name: Build Serving image
        run: docker build -t mlops/api:ci -f docker/serving/Dockerfile .

      - name: Build Nginx image
        run: docker build -t mlops/nginx:ci -f docker/nginx/Dockerfile .
```

**우선순위**: 높음

---

## 우선순위 요약

| # | 항목 | 레이어 | 우선순위 |
|---|------|--------|--------|
| 3 | Grafana Alerting 미구성 | 모니터링 | 높음 |
| 4 | Evidently 드리프트 자동 스케줄링 | 모니터링 | 높음 |
| 9 | GitHub Actions CI 파이프라인 | CI/CD | 높음 |
| 1 | Gunicorn 다중 워커 reload 불일치 | 서빙 | 중간 |
| 2 | Prometheus retention 미설정 | 모니터링 | 중간 |
| 5 | E2E 테스트 미작성 | 테스트 | 중간 |
| 6 | Locust 부하 테스트 미작성 | 테스트 | 중간 |
| 7 | Postgres healthcheck start_period | 인프라 | 낮음 |
| 8 | MinIO 버킷 버전 관리 | 인프라 | 낮음 |
