"""Pin the ``CT_MIN_ANNOTATION_COUNT`` env override contract.

The iter-5 webhook happy-path E2E depends on a dev-only env override:
``CT_MIN_ANNOTATION_COUNT=1`` relaxes the 50-annotation threshold in
``ContinuousTrainingConfig`` so a minimally seeded Label Studio project
(1 task with 1 annotation from the seed script) still satisfies
``count >= min_annotation_count``. If a future refactor ever makes
``min_annotation_count`` immutable or type-coerces the env value
incorrectly, the webhook happy path would silently regress back to
"always drop the trigger" — same silent-failure class as the problems
this roadmap has been closing all along.

Note: the lower bound stays at ``ge=1`` in the Pydantic field. Zero is
explicitly rejected because firing retrainings on empty projects is a
production footgun. The dev E2E uses the minimum-valid value (``1``)
paired with 1 seeded annotation to exercise the real happy path.

One assertion per invariant:

1. ``CT_MIN_ANNOTATION_COUNT=1`` round-trips through Pydantic Settings.
2. Default stays at ``50`` when the env var is unset (production
   semantics unchanged).
3. ``CT_MIN_ANNOTATION_COUNT=0`` is rejected loud — this is the invariant
   that forced iter 5 to pivot from "empty project + count=0 bypass"
   to "seed 1 annotation + count=1 threshold", and pinning it prevents
   a future refactor from silently re-opening the footgun.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestMinAnnotationCountEnvOverride:
    def test_one_override_is_honored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CT_MIN_ANNOTATION_COUNT", "1")
        from src.core.orchestration.config import ContinuousTrainingConfig

        cfg = ContinuousTrainingConfig()
        assert cfg.min_annotation_count == 1

    def test_default_still_fifty_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CT_MIN_ANNOTATION_COUNT", raising=False)
        from src.core.orchestration.config import ContinuousTrainingConfig

        cfg = ContinuousTrainingConfig()
        assert cfg.min_annotation_count == 50

    def test_zero_override_is_rejected_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero is not allowed — production should never fire retrainings
        on an empty project. Pydantic ``Field(ge=1)`` raises loud."""
        monkeypatch.setenv("CT_MIN_ANNOTATION_COUNT", "0")
        from src.core.orchestration.config import ContinuousTrainingConfig

        with pytest.raises(ValidationError, match="greater_than_equal"):
            ContinuousTrainingConfig()
