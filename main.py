"""
NewsLeader Radio — entry point (for local development).

Production: use gunicorn via wsgi.py (see Dockerfile CMD).
"""
import os
import sys
import signal
import logging

import structlog
from dotenv import load_dotenv

load_dotenv()

from config import config
from streaming.server import create_app
from pipeline.queue_manager import playback_loop
from scheduler.program_clock import program_clock


def _configure_logging() -> None:
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
    logging.getLogger("htmldate").setLevel(logging.CRITICAL)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
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


def main() -> None:
    _configure_logging()
    log = structlog.get_logger("main")

    log.info("newsleader_starting", port=config.PORT)
    playback_loop.start()
    program_clock.start()

    app = create_app()

    def _shutdown(signum, frame):
        log.info("shutdown_signal", signal=signum)
        program_clock.stop()
        playback_loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    app.run(host=config.HOST, port=config.PORT, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    main()
