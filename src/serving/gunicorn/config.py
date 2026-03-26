"""Gunicorn configuration for the inference API.

This file is loaded by Gunicorn via the -c flag:
    gunicorn -c src/serving/gunicorn/config.py src.serving.api.app:create_app()

All variables at module level are Gunicorn settings.
See: https://docs.gunicorn.org/en/stable/settings.html
"""

import multiprocessing
import os

# Server socket
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", min(2 * multiprocessing.cpu_count() + 1, 4)))
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
