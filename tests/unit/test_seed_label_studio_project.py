"""Unit tests for ``scripts/seed_label_studio_project.py``.

The seeding script is the bridge between an empty Label Studio container and
the webhook happy-path E2E: it gets-or-creates an admin user via Django shell
(or accepts a pre-existing token), creates-or-reuses a minimal project,
seeds one annotated task so the handler's ``count >= min_annotation_count``
check can pass, and prints the credentials to stdout. These tests pin the
strategy-chain contract so future edits don't silently break the fallback
order or the stdout shape the runtime E2E relies on.

All tests mock out subprocess / httpx.Client — no real HTTP traffic,
no real ``docker compose exec`` calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.seed_label_studio_project import (
    SeedConfig,
    _authenticate,
    _ensure_at_least_one_annotation,
    _refresh_project_counters,
    _resolve_project_id,
    _strategy_compose_django_shell,
    _strategy_preexisting_token,
)


@pytest.fixture
def cfg() -> SeedConfig:
    """Deterministic test config — avoids hitting environment defaults."""
    return SeedConfig(
        url="http://label-studio-test:8080",
        username="admin@test.local",
        password="test-pass-1234",  # noqa: S106 — test fixture
        project_title="test-project",
        user_token="",
        compose_service="label-studio",
    )


def _make_response(status_code: int, json_body: dict | list | None = None) -> MagicMock:
    """Build a minimal httpx.Response-shaped mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = str(json_body) if json_body else ""
    resp.raise_for_status.return_value = None
    return resp


class TestPreexistingTokenStrategy:
    """Strategy 1: LABEL_STUDIO_USER_TOKEN env var short-circuits auth."""

    def test_returns_none_when_token_env_is_empty(self, cfg: SeedConfig) -> None:
        assert _strategy_preexisting_token(cfg) is None

    def test_returns_token_when_env_has_hex_token(self, cfg: SeedConfig) -> None:
        cfg_with_token = SeedConfig(
            **{**cfg.__dict__, "user_token": "a" * 40},
        )
        assert _strategy_preexisting_token(cfg_with_token) == "a" * 40

    def test_accepts_non_hex_token_with_warning(self, cfg: SeedConfig) -> None:
        """The script warns but still trusts a non-hex token so future LS
        versions with a different token format keep working."""
        cfg_custom = SeedConfig(
            **{**cfg.__dict__, "user_token": "not-hex-but-valid"},
        )
        assert _strategy_preexisting_token(cfg_custom) == "not-hex-but-valid"


class TestComposeDjangoShellStrategy:
    """Strategy 2: docker compose exec + Django shell ORM manipulation."""

    def test_returns_token_on_success(self, cfg: SeedConfig) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = (
            "...lots of import noise...\n"
            "TOKEN:51812fbfb9b992dc2266b162cb924f6af7dd427e\n"
            "now exiting InteractiveConsole...\n"
        )
        fake_result.stderr = ""
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            token = _strategy_compose_django_shell(cfg)
        assert token == "51812fbfb9b992dc2266b162cb924f6af7dd427e"

    def test_returns_none_on_subprocess_nonzero_exit(self, cfg: SeedConfig) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = ""
        fake_result.stderr = "docker: command not found"
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            token = _strategy_compose_django_shell(cfg)
        assert token is None

    def test_returns_none_when_no_token_marker_in_output(
        self, cfg: SeedConfig
    ) -> None:
        """The shell ran successfully but the snippet produced no TOKEN:
        marker (e.g. the Django snippet raised silently)."""
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "some unrelated output\n"
        fake_result.stderr = ""
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            token = _strategy_compose_django_shell(cfg)
        assert token is None

    def test_returns_none_when_docker_missing(self, cfg: SeedConfig) -> None:
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            token = _strategy_compose_django_shell(cfg)
        assert token is None


class TestAuthenticationStrategyChain:
    """Pins strategy-1 -> strategy-2 -> strategy-3 fallback order."""

    def test_strategy_1_short_circuits_when_token_env_set(
        self, cfg: SeedConfig
    ) -> None:
        cfg_with_token = SeedConfig(
            **{**cfg.__dict__, "user_token": "b" * 40},
        )
        with patch(
            "scripts.seed_label_studio_project._strategy_compose_django_shell",
        ) as mock_compose:
            token = _authenticate(cfg_with_token)
        assert token == "b" * 40
        mock_compose.assert_not_called()

    def test_falls_through_to_strategy_2_when_no_token_env(
        self, cfg: SeedConfig
    ) -> None:
        with patch(
            "scripts.seed_label_studio_project._strategy_compose_django_shell",
            return_value="c" * 40,
        ):
            token = _authenticate(cfg)
        assert token == "c" * 40

    def test_all_strategies_fail_raises_runtimeerror(
        self, cfg: SeedConfig
    ) -> None:
        with (
            patch(
                "scripts.seed_label_studio_project._strategy_compose_django_shell",
                return_value=None,
            ),
            patch(
                "scripts.seed_label_studio_project._strategy_playwright_signup",
                return_value=None,
            ),
            pytest.raises(
                RuntimeError, match="All authentication strategies failed"
            ),
        ):
            _authenticate(cfg)


class TestProjectResolution:
    """Idempotent project lookup/creation."""

    def test_reuses_existing_project_by_title(self, cfg: SeedConfig) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _make_response(
            200,
            [
                {"id": 42, "title": "test-project"},
                {"id": 7, "title": "other-project"},
            ],
        )
        project_id = _resolve_project_id(mock_client, cfg)
        assert project_id == 42
        mock_client.post.assert_not_called()

    def test_creates_new_project_on_empty_list(self, cfg: SeedConfig) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _make_response(200, [])
        mock_client.post.return_value = _make_response(201, {"id": 99})
        project_id = _resolve_project_id(mock_client, cfg)
        assert project_id == 99
        mock_client.post.assert_called_once()
        body = mock_client.post.call_args.kwargs["json"]
        assert body["title"] == "test-project"
        assert "<View>" in body["label_config"]
        assert "<Image" in body["label_config"]

    def test_paginated_response_shape_also_reused(self, cfg: SeedConfig) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _make_response(
            200,
            {"results": [{"id": 13, "title": "test-project"}]},
        )
        project_id = _resolve_project_id(mock_client, cfg)
        assert project_id == 13
        mock_client.post.assert_not_called()


class TestAnnotationSeeding:
    """The minimum-viable E2E requires >= 1 task + 1 annotation because
    ``ContinuousTrainingConfig.min_annotation_count`` is ``ge=1``."""

    def test_existing_annotations_skips_import(self, cfg: SeedConfig) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _make_response(
            200, {"id": 1, "num_tasks_with_annotations": 5}
        )
        count = _ensure_at_least_one_annotation(mock_client, cfg, 1)
        assert count == 5
        mock_client.post.assert_not_called()

    def test_empty_project_seeds_one_task_with_embedded_annotation(
        self, cfg: SeedConfig
    ) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = [
            _make_response(200, {"id": 1, "num_tasks_with_annotations": 0}),
            _make_response(200, {"id": 1, "num_tasks_with_annotations": 1}),
        ]
        mock_client.post.return_value = _make_response(200, {"task_count": 1})
        with patch(
            "scripts.seed_label_studio_project._refresh_project_counters",
            return_value=1,
        ) as mock_refresh:
            count = _ensure_at_least_one_annotation(mock_client, cfg, 1)
        assert count == 1
        mock_refresh.assert_called_once_with(cfg, 1)
        mock_client.post.assert_called_once()
        post_url = mock_client.post.call_args.args[0]
        assert "/api/projects/1/import" in post_url
        body = mock_client.post.call_args.kwargs["json"]
        assert isinstance(body, list) and len(body) == 1
        item = body[0]
        assert "data" in item and "image" in item["data"]
        assert "annotations" in item
        result = item["annotations"][0]["result"]
        assert result[0]["type"] == "choices"
        assert result[0]["from_name"] == "label"
        assert result[0]["to_name"] == "image"

    def test_seed_failure_returns_zero_count(self, cfg: SeedConfig) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = [
            _make_response(200, {"id": 1, "num_tasks_with_annotations": 0}),
            _make_response(200, {"id": 1, "num_tasks_with_annotations": 0}),
        ]
        mock_client.post.return_value = _make_response(200, {})
        with patch(
            "scripts.seed_label_studio_project._refresh_project_counters",
            return_value=None,
        ):
            count = _ensure_at_least_one_annotation(mock_client, cfg, 1)
        assert count == 0  # pathological case — main() raises RuntimeError


class TestCounterRefresh:
    """``_refresh_project_counters`` is the missing-link helper that closes
    the Label Studio 1.19 signal-chain gap: REST ``/api/projects/{id}/import``
    creates Task+Annotation rows but never bumps ``num_tasks_with_annotations``
    on the project row. The helper shells into the label-studio container and
    calls ``Project.update_tasks_counters_and_is_labeled()`` directly on the
    ORM, then echoes ``COUNTERS_REFRESHED:<n>`` for the caller to parse."""

    def test_returns_int_on_success(self, cfg: SeedConfig) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = (
            "...django shell banner...\n"
            "COUNTERS_REFRESHED:1\n"
            "now exiting InteractiveConsole...\n"
        )
        fake_result.stderr = ""
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ) as mock_run:
            refreshed = _refresh_project_counters(cfg, 1)
        assert refreshed == 1
        # Ensure the helper targets the label-studio service via compose exec.
        args = mock_run.call_args.args[0]
        assert "docker" in args
        assert "exec" in args
        assert cfg.compose_service in args
        assert "shell" in args

    def test_returns_none_on_nonzero_exit(self, cfg: SeedConfig) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = ""
        fake_result.stderr = "docker daemon not reachable"
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            refreshed = _refresh_project_counters(cfg, 1)
        assert refreshed is None

    def test_returns_none_when_docker_missing(self, cfg: SeedConfig) -> None:
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            refreshed = _refresh_project_counters(cfg, 1)
        assert refreshed is None

    def test_returns_none_when_no_marker_in_output(
        self, cfg: SeedConfig
    ) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "unrelated stdout with no marker\n"
        fake_result.stderr = ""
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            refreshed = _refresh_project_counters(cfg, 1)
        assert refreshed is None

    def test_returns_none_when_marker_has_non_integer_value(
        self, cfg: SeedConfig
    ) -> None:
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "COUNTERS_REFRESHED:NaN\n"
        fake_result.stderr = ""
        with patch(
            "scripts.seed_label_studio_project.subprocess.run",
            return_value=fake_result,
        ):
            refreshed = _refresh_project_counters(cfg, 1)
        assert refreshed is None
