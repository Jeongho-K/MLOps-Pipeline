"""Gunicorn configuration for the inference API.

This file is loaded by Gunicorn via the -c flag:
    gunicorn -c src/core/serving/gunicorn/config.py src.core.serving.api.app:create_app()

All variables at module level are Gunicorn settings.
See: https://docs.gunicorn.org/en/stable/settings.html
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gunicorn.arbiter import Arbiter
    from gunicorn.workers.base import Worker


def on_starting(server: Arbiter) -> None:
    """Prepare ``PROMETHEUS_MULTIPROC_DIR`` before workers fork.

    prometheus_client writes per-process mmap files here. The directory
    must exist and be empty at start to avoid carrying stale counters
    from a previous invocation.

    Args:
        server: The gunicorn ``Arbiter`` instance owning the worker pool.
    """
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    path = Path(multiproc_dir)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    server.log.info("Initialized PROMETHEUS_MULTIPROC_DIR at %s", path)


def child_exit(server: Arbiter, worker: Worker) -> None:
    """Mark worker as dead for prometheus_client multiprocess mode.

    Prevents stale mmap files from dead workers affecting aggregated
    metrics.

    Args:
        server: The gunicorn ``Arbiter`` instance.
        worker: The exiting gunicorn ``Worker`` instance.
    """
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    try:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
    except Exception as exc:  # pragma: no cover
        server.log.warning("Failed to mark worker %s dead: %s", worker.pid, exc)


# Server socket
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", str(min(2 * multiprocessing.cpu_count() + 1, 4))))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# Process naming
proc_name = "mlops-inference-api"

# Preload app to share model memory across workers (copy-on-write)
preload_app = False  # False because each worker needs its own CUDA context
