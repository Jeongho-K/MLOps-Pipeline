"""Seed a Label Studio project + fetch an API token for dev/E2E.

Label Studio 1.19 does NOT auto-create an admin user from env vars, and the
``LabelStudioBridge`` class does not expose a ``create_project`` method.
Worse, Label Studio 1.19's auth endpoints are Django form-based (POST to
``/user/login`` and ``/user/signup`` with CSRF + form-encoding) — not the
JSON APIs some docs suggest. This script closes that gap so the webhook
happy-path E2E (POST ``/webhooks/label-studio`` -> ``run_deployment`` fires)
can run end-to-end against a real Label Studio instance without manual UI
clicks.

The script tries three authentication strategies in order and stops at the
first one that works:

1. **Pre-existing token**: if ``LABEL_STUDIO_USER_TOKEN`` is set in the
   environment, use it directly. This is the fast path for scripted re-runs
   after the token has been retrieved once.

2. **Docker exec Django shell**: run a small Python snippet inside the
   ``label-studio`` compose container that gets-or-creates the admin user
   (with organization + active_organization wiring), then fetches the
   ``rest_framework.authtoken.models.Token`` for that user. Reliable on
   Label Studio 1.19 because it bypasses the Django form endpoints entirely
   and operates directly on the ORM.

3. **Playwright headed Chrome fallback**: drive the ``/user/signup`` form
   manually if the operator is running the script from outside the compose
   stack and ``docker compose exec`` is not available.

After authentication the script:

- Looks up a project by title (default ``data-flywheel-dev``). If one exists,
  reuses its ID (idempotent — re-running the script does not create duplicates).
- Otherwise POSTs a minimal CV classification label config
  (``<View><Image/><Choices.../></View>``) and reads the new project ID.
- Ensures the project has >= 1 task with >= 1 annotation so the webhook
  handler's ``count >= config.min_annotation_count`` check (Pydantic ``ge=1``)
  can pass on an otherwise-fresh project.

On success it prints two lines to **stdout** that operators can `source` or
append to `.env.local`::

    CT_LABEL_STUDIO_API_KEY=<token>
    CT_LABEL_STUDIO_PROJECT_ID=<id>

All informational logging goes to **stderr** so stdout stays pipe-clean.

Usage:
    uv run python scripts/seed_label_studio_project.py
    uv run python scripts/seed_label_studio_project.py --url http://localhost:8081
    source <(uv run python scripts/seed_label_studio_project.py)

Env:
    LABEL_STUDIO_URL         (default: http://localhost:8081)
    LABEL_STUDIO_USERNAME    (default: admin@localhost)
    LABEL_STUDIO_PASSWORD    (default: admin1234)
    LABEL_STUDIO_USER_TOKEN  (default: unset — strategy 1 skipped if empty)
    LABEL_STUDIO_COMPOSE_SERVICE  (default: label-studio — docker compose service name)
    LABEL_STUDIO_PROJECT_TITLE (default: data-flywheel-dev)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass

import httpx

logger = logging.getLogger("seed_label_studio_project")


DEFAULT_URL = "http://localhost:8081"
DEFAULT_USERNAME = "admin@localhost"
DEFAULT_PASSWORD = "admin1234"  # noqa: S105 — dev-only default
DEFAULT_PROJECT_TITLE = "data-flywheel-dev"

# Minimal CV image-classification label config. The webhook handler only
# needs `num_tasks_with_annotations` from the project stats endpoint, so the
# label schema just has to be syntactically valid Label Studio XML.
DEFAULT_LABEL_CONFIG = (
    '<View>'
    '<Image name="image" value="$image"/>'
    '<Choices name="label" toName="image">'
    '<Choice value="cat"/>'
    '<Choice value="dog"/>'
    '</Choices>'
    '</View>'
)


@dataclass(frozen=True)
class SeedConfig:
    """Runtime parameters for the seeding script."""

    url: str
    username: str
    password: str
    project_title: str
    user_token: str
    compose_service: str


def _configure_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _load_config() -> SeedConfig:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--url",
        default=os.environ.get("LABEL_STUDIO_URL", DEFAULT_URL),
        help="Label Studio base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("LABEL_STUDIO_USERNAME", DEFAULT_USERNAME),
        help="Admin email (default: %(default)s)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("LABEL_STUDIO_PASSWORD", DEFAULT_PASSWORD),
        help="Admin password (default: *** hidden ***)",
    )
    parser.add_argument(
        "--project-title",
        default=os.environ.get("LABEL_STUDIO_PROJECT_TITLE", DEFAULT_PROJECT_TITLE),
        help="Project title to look up or create (default: %(default)s)",
    )
    parser.add_argument(
        "--user-token",
        default=os.environ.get("LABEL_STUDIO_USER_TOKEN", ""),
        help="Pre-existing DRF token (skips auth strategies if set)",
    )
    parser.add_argument(
        "--compose-service",
        default=os.environ.get("LABEL_STUDIO_COMPOSE_SERVICE", "label-studio"),
        help="Docker compose service name for the Django shell fallback",
    )
    args = parser.parse_args()
    return SeedConfig(
        url=args.url.rstrip("/"),
        username=args.username,
        password=args.password,
        project_title=args.project_title,
        user_token=args.user_token,
        compose_service=args.compose_service,
    )


# Token pattern: DRF tokens are 40 hex characters. Used to validate the
# output of the Django shell one-liner.
_TOKEN_RE = re.compile(r"^[0-9a-f]{40}$")

# Django shell payload. Each ``if``/``else`` block is followed by a
# mandatory blank line so the ``label-studio shell`` interactive REPL
# closes the block before parsing the next top-level statement. Without
# the blank line (even with semicolon-packed bodies), Python's REPL
# treats the subsequent ``token, _ = ...`` line as part of the previous
# suite and raises SyntaxError. A matched ``else: pass`` plus a blank
# line is the only pattern that reliably flows through the REPL for
# Label Studio 1.19's shell_plus wrapper.
#
# The body:
#   1. Gets or creates the admin user with the given email/password
#   2. On creation, sets up a new Organization and links it as the user's
#      active_organization (Label Studio requires this for API writes)
#   3. Gets or creates the DRF auth token for that user
#   4. Prints a single line ``TOKEN:<hex>`` that the wrapper greps for
_DJANGO_SHELL_SNIPPET = (
    "from users.models import User\n"
    "from rest_framework.authtoken.models import Token\n"
    "from organizations.models import Organization\n"
    "from jwt_auth.models import JWTSettings\n"
    "email = {email!r}\n"
    "password = {password!r}\n"
    "user, created = User.objects.get_or_create("
    "email=email, "
    "defaults={{"
    "'username': email, "
    "'first_name': 'Admin', "
    "'last_name': 'User', "
    "'is_staff': True, "
    "'is_superuser': True, "
    "'is_active': True"
    "}})\n"
    "if created:\n"
    "    user.set_password(password)\n"
    "    user.save()\n"
    "    org = Organization.create_organization("
    "created_by=user, title='Data Flywheel Dev')\n"
    "    user.active_organization = org\n"
    "    user.save()\n"
    "else:\n"
    "    pass\n"
    "\n"  # blank line closes the if/else block in the REPL
    "jwt_settings, _ = JWTSettings.objects.get_or_create("
    "organization=user.active_organization, "
    "defaults={{'api_tokens_enabled': True, 'legacy_api_tokens_enabled': True}})\n"
    "jwt_settings.legacy_api_tokens_enabled = True\n"
    "jwt_settings.save()\n"
    "token, _ = Token.objects.get_or_create(user=user)\n"
    "print('TOKEN:' + token.key)\n"
)


# Django shell payload that flips any leftover ``ground_truth=True``
# annotations in the project to ``ground_truth=False``. This is the
# fallback cleanup path for stale seeds created before the import payload
# was fixed to pass ``ground_truth: False`` explicitly. Label Studio 1.19's
# ``num_tasks_with_annotations`` subquery filters on
# ``ground_truth=False AND was_cancelled=False AND result__isnull=False``
# (see ``projects/functions/__init__.py::annotate_num_tasks_with_annotations``),
# so annotations stuck at ``ground_truth=True`` are invisible to the
# counter that ``LabelStudioBridge.get_annotation_count`` reads.
#
# The script prints a ``COUNTERS_REFRESHED:<n>`` line where ``<n>`` is the
# post-flip ``num_tasks_with_annotations`` value computed by the same
# subquery (so the caller gets authoritative state).
_COUNTER_REFRESH_SNIPPET = (
    "from tasks.models import Annotation\n"
    "from projects.models import Project\n"
    "from projects.functions import annotate_num_tasks_with_annotations\n"
    "flipped = Annotation.objects.filter(project_id={project_id}, ground_truth=True).update(ground_truth=False)\n"
    "p = annotate_num_tasks_with_annotations(Project.objects.filter(pk={project_id})).first()\n"
    "print('COUNTERS_REFRESHED:' + str(p.num_tasks_with_annotations))\n"
    "print('FLIPPED:' + str(flipped))\n"
)


def _strategy_preexisting_token(cfg: SeedConfig) -> str | None:
    """Strategy 1: use a token the operator already has on hand."""
    if not cfg.user_token:
        return None
    if not _TOKEN_RE.match(cfg.user_token):
        logger.warning(
            "LABEL_STUDIO_USER_TOKEN is set but does not look like a DRF "
            "token (expected 40 hex chars); trying it anyway"
        )
    logger.info("strategy 1: using pre-existing LABEL_STUDIO_USER_TOKEN")
    return cfg.user_token


def _strategy_compose_django_shell(cfg: SeedConfig) -> str | None:
    """Strategy 2: docker compose exec into the label-studio container and
    run a small Django shell snippet to create-or-update the admin user,
    then fetch the DRF token.

    This is the most reliable strategy for Label Studio 1.19 because it
    bypasses the Django form-based ``/user/login`` and ``/user/signup``
    endpoints entirely and operates directly on the ORM.
    """
    logger.info(
        "strategy 2: docker compose exec -> django shell on service %s",
        cfg.compose_service,
    )

    snippet = _DJANGO_SHELL_SNIPPET.format(
        email=cfg.username,
        password=cfg.password,
    )

    try:
        result = subprocess.run(  # noqa: S603 — cmd is assembled from internal strings
            [
                "docker",
                "compose",
                "exec",
                "-T",
                cfg.compose_service,
                "label-studio",
                "shell",
            ],
            input=snippet,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        logger.warning("strategy 2: `docker` binary not on PATH; skipping")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("strategy 2: docker compose exec timed out after 120s")
        return None

    if result.returncode != 0:
        logger.warning(
            "strategy 2: docker compose exec failed (rc=%d): %s",
            result.returncode,
            (result.stderr or "")[:200],
        )
        return None

    # The Django shell prints a lot of imports before our output. Scan the
    # combined output for the TOKEN: marker.
    combined = (result.stdout or "") + (result.stderr or "")
    for line in combined.splitlines():
        marker = "TOKEN:"
        idx = line.find(marker)
        if idx >= 0:
            token = line[idx + len(marker) :].strip()
            if token and _TOKEN_RE.match(token):
                logger.info("strategy 2: Django shell returned a valid token")
                return token
            if token:
                logger.warning(
                    "strategy 2: Django shell returned a non-hex token: %s",
                    token,
                )
                return token  # trust it, Label Studio may have changed format

    logger.warning(
        "strategy 2: Django shell ran but no TOKEN: marker found in output"
    )
    return None


def _strategy_playwright_signup(cfg: SeedConfig) -> str | None:
    """Strategy 3: headed Chrome signup via Playwright (last-resort fallback).

    Mirrors the browser flow in ``tests/e2e/browser/conftest.py``. Requires
    the ``playwright`` package (already installed as a dev dependency).
    Used when the operator is running the script from outside the compose
    stack and ``docker compose exec`` is not available.
    """
    logger.info("strategy 3: playwright signup fallback")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("strategy 3: playwright not available, cannot fall back")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, channel="chrome")
            context = browser.new_context()
            page = context.new_page()
            page.goto(f"{cfg.url}/user/signup")
            page.fill('input[name="email"]', cfg.username)
            page.fill('input[name="password"]', cfg.password)
            try:
                page.select_option('select[name="how_find_us"]', "Other")
            except Exception as exc:  # noqa: BLE001
                logger.warning("strategy 3: could not select how_find_us: %s", exc)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=10_000)
            cookies = {c["name"]: c["value"] for c in context.cookies()}
            browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("strategy 3: playwright flow failed: %s", exc)
        return None

    # After signup, the Django session cookie should let us hit the DRF
    # token endpoint.
    with httpx.Client(cookies=cookies, timeout=10.0) as client:
        try:
            resp = client.get(f"{cfg.url}/api/current-user/token")
            if resp.status_code < 400:
                token = resp.json().get("token")
                if token:
                    logger.info("strategy 3: playwright + token fetch successful")
                    return token
            logger.warning(
                "strategy 3: token fetch after playwright failed: status=%d",
                resp.status_code,
            )
        except httpx.HTTPError as exc:
            logger.warning("strategy 3: token fetch transport error: %s", exc)
    return None


def _authenticate(cfg: SeedConfig) -> str:
    """Run the strategy chain and return a working DRF token.

    Raises:
        RuntimeError: if all three strategies fail.
    """
    for strategy in (
        _strategy_preexisting_token,
        _strategy_compose_django_shell,
        _strategy_playwright_signup,
    ):
        token = strategy(cfg)
        if token:
            return token

    raise RuntimeError(
        "All authentication strategies failed. Check that Label Studio is "
        f"reachable at {cfg.url} and that `docker compose exec "
        f"{cfg.compose_service}` works from the current directory. "
        f"Last-resort: sign up manually in the browser at {cfg.url}/user/signup, "
        "read the token from the UI, and re-run with "
        "LABEL_STUDIO_USER_TOKEN=<hex> to use strategy 1."
    )


def _refresh_project_counters(cfg: SeedConfig, project_id: int) -> int | None:
    """Fallback cleanup for pre-existing ``ground_truth=True`` annotations.

    ``num_tasks_with_annotations`` is NOT a stored Project field — it's
    computed by a subquery at serialization time that filters
    ``ground_truth=False AND was_cancelled=False AND result__isnull=False``
    (``projects/functions/__init__.py::annotate_num_tasks_with_annotations``).
    New imports done via :func:`_ensure_at_least_one_annotation` already
    pass ``ground_truth: False`` explicitly, so the counter reflects them
    immediately. But any annotations that were seeded by an earlier
    version of this script (before the payload fix) stay invisible to the
    counter because the ``/api/projects/{id}/import`` endpoint defaults
    new annotations to ``ground_truth=True``.

    This helper shells into the label-studio container and flips any
    remaining ``ground_truth=True`` rows in the project to ``False``, then
    echoes the post-flip counter value so the caller can log/return it.

    Returns:
        The post-flip ``num_tasks_with_annotations`` integer, or ``None``
        if the Django shell call could not be made (docker missing,
        timeout, nonzero exit, or no ``COUNTERS_REFRESHED:`` marker in the
        output). The caller MAY ignore ``None`` and fall back to reading
        the counter from the REST ``/api/projects/{id}/`` endpoint; the
        dev E2E treats a stale zero as a hard failure so the webhook
        happy-path does not silently regress.
    """
    logger.info(
        "refreshing project %d counters via docker compose exec -> django shell",
        project_id,
    )
    snippet = _COUNTER_REFRESH_SNIPPET.format(project_id=project_id)

    try:
        result = subprocess.run(  # noqa: S603 — cmd is assembled from internal strings
            [
                "docker",
                "compose",
                "exec",
                "-T",
                cfg.compose_service,
                "label-studio",
                "shell",
            ],
            input=snippet,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        logger.warning(
            "counter refresh: `docker` binary not on PATH; skipping refresh"
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning("counter refresh: docker compose exec timed out after 60s")
        return None

    if result.returncode != 0:
        logger.warning(
            "counter refresh: docker compose exec failed (rc=%d): %s",
            result.returncode,
            (result.stderr or "")[:200],
        )
        return None

    combined = (result.stdout or "") + (result.stderr or "")
    for line in combined.splitlines():
        marker = "COUNTERS_REFRESHED:"
        idx = line.find(marker)
        if idx >= 0:
            raw = line[idx + len(marker) :].strip()
            try:
                refreshed = int(raw)
            except ValueError:
                logger.warning(
                    "counter refresh: non-integer counter value: %s", raw
                )
                return None
            logger.info(
                "counter refresh: project %d num_tasks_with_annotations=%d",
                project_id,
                refreshed,
            )
            return refreshed

    logger.warning(
        "counter refresh: shell ran but no COUNTERS_REFRESHED: marker found"
    )
    return None


def _resolve_project_id(
    client: httpx.Client,
    cfg: SeedConfig,
) -> int:
    """Find an existing project with the target title, or create a new one.

    Idempotent: running the script multiple times returns the same project ID
    each time, so operators can rerun safely.
    """
    # Label Studio's /api/projects list endpoint supports a title filter.
    resp = client.get(f"{cfg.url}/api/projects/", params={"title": cfg.project_title})
    resp.raise_for_status()
    payload = resp.json()

    # The endpoint can return either a list directly or a paginated envelope.
    results = payload if isinstance(payload, list) else payload.get("results", [])
    for project in results:
        if project.get("title") == cfg.project_title:
            project_id = int(project["id"])
            logger.info(
                "reused existing project: id=%d title=%s",
                project_id,
                cfg.project_title,
            )
            return project_id

    logger.info("creating new project: title=%s", cfg.project_title)
    create_resp = client.post(
        f"{cfg.url}/api/projects/",
        json={
            "title": cfg.project_title,
            "label_config": DEFAULT_LABEL_CONFIG,
        },
    )
    create_resp.raise_for_status()
    new_project = create_resp.json()
    project_id = int(new_project["id"])
    logger.info("created project: id=%d", project_id)
    return project_id


def _ensure_at_least_one_annotation(
    client: httpx.Client,
    cfg: SeedConfig,
    project_id: int,
) -> int:
    """Guarantee the project has >= 1 task with >= 1 annotation.

    The webhook handler's threshold check is
    ``count >= config.min_annotation_count`` where ``count`` is
    ``num_tasks_with_annotations`` (not total predictions). The
    ``ContinuousTrainingConfig.min_annotation_count`` field has
    ``ge=1`` validation, so the minimum viable E2E is exactly 1 task
    with 1 annotation.

    Idempotent: if the project already has annotations, no new task is
    imported. Otherwise a single task is imported with an embedded
    annotation via ``/api/projects/{id}/import`` — Label Studio accepts
    the ``annotations`` field alongside ``data`` in one POST, which
    bypasses the need for a separate ``/api/tasks/{task}/annotations/``
    call.

    Returns:
        The ``num_tasks_with_annotations`` value after seeding.
    """
    stats_resp = client.get(f"{cfg.url}/api/projects/{project_id}/")
    stats_resp.raise_for_status()
    existing = int(stats_resp.json().get("num_tasks_with_annotations", 0))
    if existing >= 1:
        logger.info(
            "project %d already has %d annotated task(s); no seed needed",
            project_id,
            existing,
        )
        return existing

    logger.info("seeding 1 task + 1 annotation into project %d", project_id)
    # CRITICAL: ``ground_truth=False`` is required or the project-level
    # ``num_tasks_with_annotations`` counter stays at 0 even after successful
    # import. Label Studio 1.19's subquery at
    # ``projects/functions/__init__.py::annotate_num_tasks_with_annotations``
    # explicitly filters out ``ground_truth=True`` annotations (only "useful"
    # human labels count). ``/api/projects/{id}/import`` defaults new
    # annotations to ``ground_truth=True``, which hides them from the
    # counter that ``LabelStudioBridge.get_annotation_count`` reads — and
    # the webhook handler's ``count >= config.min_annotation_count`` check
    # would silently fail despite the annotation being in the DB.
    import_resp = client.post(
        f"{cfg.url}/api/projects/{project_id}/import",
        json=[
            {
                "data": {"image": "https://placehold.co/224x224.png"},
                "annotations": [
                    {
                        "ground_truth": False,
                        "was_cancelled": False,
                        "result": [
                            {
                                "from_name": "label",
                                "to_name": "image",
                                "type": "choices",
                                "value": {"choices": ["cat"]},
                            }
                        ],
                    }
                ],
            }
        ],
    )
    import_resp.raise_for_status()

    # Force Label Studio to recalculate project counters. The REST import
    # path does not fire the signal chain that bumps
    # ``num_tasks_with_annotations`` on the project row, and the webhook
    # bridge reads exactly that field — without this refresh the seed would
    # appear to succeed but the happy-path E2E would still see zero.
    refreshed = _refresh_project_counters(cfg, project_id)

    # Re-fetch stats so the count we return is authoritative. If the shell
    # refresh ran we already have the post-refresh value, but the REST GET
    # is still the source of truth the webhook handler will observe.
    verify_resp = client.get(f"{cfg.url}/api/projects/{project_id}/")
    verify_resp.raise_for_status()
    count = int(verify_resp.json().get("num_tasks_with_annotations", 0))
    if refreshed is not None and count != refreshed:
        logger.warning(
            "counter divergence: refresh returned %d but REST returned %d",
            refreshed,
            count,
        )
    logger.info(
        "post-seed annotation count: %d (project %d)",
        count,
        project_id,
    )
    return count


def main() -> None:
    _configure_logging()
    cfg = _load_config()
    logger.info("seeding Label Studio at %s", cfg.url)

    token = _authenticate(cfg)

    with httpx.Client(
        timeout=10.0,
        headers={"Authorization": f"Token {token}"},
    ) as authed_client:
        project_id = _resolve_project_id(authed_client, cfg)
        annotation_count = _ensure_at_least_one_annotation(
            authed_client, cfg, project_id
        )

    if annotation_count < 1:
        raise RuntimeError(
            f"Post-seed annotation count for project {project_id} is "
            f"{annotation_count}, expected >= 1. The webhook happy-path "
            "E2E requires num_tasks_with_annotations >= "
            "CT_MIN_ANNOTATION_COUNT, which has Pydantic ge=1."
        )

    # Stdout contract: exactly two lines that can be sourced. Keep out of the
    # logger so the stderr log stream doesn't pollute stdout.
    sys.stdout.write(f"CT_LABEL_STUDIO_API_KEY={token}\n")
    sys.stdout.write(f"CT_LABEL_STUDIO_PROJECT_ID={project_id}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
