"""
Gunicorn WSGI entry point.

Starts background threads (playback loop + scheduler) on first import,
then exposes the Flask `app` for gunicorn to serve.
"""
import os
import sys
import logging

import structlog
from dotenv import load_dotenv

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("wsgi")

# ── Background services ───────────────────────────────────────────────────────
from pipeline.queue_manager import playback_loop
from scheduler.program_clock import program_clock
from streaming.server import create_app

log.info("starting_background_services")
playback_loop.start()
program_clock.start()

# ── Flask app (exposed to gunicorn) ──────────────────────────────────────────
app = create_app()
log.info("wsgi_ready", port=8000)
