"""
Health, status, and metrics endpoints.

GET /health   — liveness probe with detailed checks
GET /status   — full JSON status (queue, listeners, pipeline)
GET /metrics  — Prometheus text format (no library needed)
"""
import time
import threading
from datetime import datetime
from flask import Flask, jsonify, Response
import structlog

log = structlog.get_logger(__name__)

_start_time = time.time()

# ── Lightweight counters (no prometheus-client needed) ────────────────────────

_counters: dict[str, int] = {
    "articles_fetched":    0,
    "scripts_generated":   0,
    "scripts_qa_failed":   0,
    "tts_completed":       0,
    "tts_errors":          0,
    "llm_errors":          0,
    "pipeline_runs":       0,
    "pipeline_errors":     0,
    "chunks_dropped":      0,
    "breaking_news":       0,
    "feed_304s":           0,
}
_lock = threading.Lock()

# Last pipeline run timestamp (epoch)
_last_pipeline_run: float = 0.0
_last_pipeline_success: bool = True


def increment(name: str, by: int = 1) -> None:
    """Thread-safe counter increment. Call from any module."""
    with _lock:
        if name in _counters:
            _counters[name] += by


def set_pipeline_run(success: bool) -> None:
    """Record a pipeline run result."""
    global _last_pipeline_run, _last_pipeline_success
    with _lock:
        _last_pipeline_run = time.time()
        _last_pipeline_success = success
    increment("pipeline_runs")
    if not success:
        increment("pipeline_errors")


# ── Flask routes ──────────────────────────────────────────────────────────────

def register_routes(app: Flask) -> None:

    @app.route("/health")
    def health():
        from streaming.broadcaster import broadcaster
        from pipeline.queue_manager import audio_queue

        uptime = round(time.time() - _start_time)
        q_sec = round(audio_queue.buffered_seconds, 1)
        listeners = broadcaster.listener_count
        with _lock:
            last_run_ago = round(time.time() - _last_pipeline_run) if _last_pipeline_run else None
            last_ok = _last_pipeline_success

        # Overall status
        queue_ok = q_sec > 30 or listeners == 0   # not critical if no listeners
        pipeline_ok = last_run_ago is None or last_run_ago < 1800  # ran within 30 min

        status = "ok" if (queue_ok and pipeline_ok) else "degraded"

        return jsonify({
            "status": status,
            "uptime_s": uptime,
            "checks": {
                "queue_seconds": q_sec,
                "queue_ok": queue_ok,
                "listeners": listeners,
                "pipeline_last_run_ago_s": last_run_ago,
                "pipeline_last_success": last_ok,
                "pipeline_ok": pipeline_ok,
            },
        }), 200 if status == "ok" else 503

    @app.route("/status")
    def status():
        from streaming.broadcaster import broadcaster
        from pipeline.queue_manager import audio_queue

        with _lock:
            counters = dict(_counters)
            last_run_ago = round(time.time() - _last_pipeline_run) if _last_pipeline_run else None

        return jsonify({
            "status": "ok",
            "uptime_s": round(time.time() - _start_time),
            "listeners": broadcaster.listener_count,
            "now_playing": audio_queue.current_title,
            "queue": {
                "buffered_seconds": round(audio_queue.buffered_seconds, 1),
                "watermark": audio_queue.watermark_status(),
                "is_critical": audio_queue.is_critical(),
                "is_low":  audio_queue.is_low(),
                "is_full": audio_queue.is_full(),
            },
            "pipeline": {
                "last_run_ago_s": last_run_ago,
                "last_success":   _last_pipeline_success,
            },
            "counters": counters,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }), 200

    @app.route("/metrics")
    def metrics():
        """Prometheus text format — no library needed."""
        from streaming.broadcaster import broadcaster
        from pipeline.queue_manager import audio_queue

        with _lock:
            counters = dict(_counters)

        lines = [
            "# HELP newsleader_uptime_seconds Process uptime",
            "# TYPE newsleader_uptime_seconds gauge",
            f"newsleader_uptime_seconds {round(time.time() - _start_time)}",

            "# HELP newsleader_listeners_total Active streaming listeners",
            "# TYPE newsleader_listeners_total gauge",
            f"newsleader_listeners_total {broadcaster.listener_count}",

            "# HELP newsleader_queue_seconds Buffered audio in queue",
            "# TYPE newsleader_queue_seconds gauge",
            f"newsleader_queue_seconds {round(audio_queue.buffered_seconds, 1)}",

            "# HELP newsleader_queue_watermark Buffer watermark level (0=ok,1=low,2=critical,3=full)",
            "# TYPE newsleader_queue_watermark gauge",
        ]
        _wm_map = {"ok": 0, "low": 1, "critical": 2, "full": 3}
        lines += [
            f"newsleader_queue_watermark {_wm_map.get(audio_queue.watermark_status(), 0)}",
        ]

        # All counters
        for name, value in counters.items():
            metric = f"newsleader_{name}_total"
            lines += [
                f"# TYPE {metric} counter",
                f"{metric} {value}",
            ]

        return Response("\n".join(lines) + "\n", mimetype="text/plain; charset=utf-8")
