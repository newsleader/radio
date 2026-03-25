"""
Lightweight distributed tracing for NewsLeader.

Uses OpenTelemetry SDK if installed; falls back to a no-op stub if not.
Traces key operations:
  - content pipeline runs (span: pipeline.run)
  - RSS fetch per feed (span: fetcher.fetch_feed)
  - LLM script generation (span: llm.generate_script)
  - TTS synthesis (span: tts.synthesize)

Installation (optional — adds ~15MB):
  pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

Without installation: all trace calls are no-ops with zero overhead.

To view traces: set OTEL_EXPORTER_OTLP_ENDPOINT env var to point to
your collector (e.g. Jaeger, Grafana Tempo).
If not set, traces are exported to console in dev mode.
"""
import os
import time
import contextlib

import structlog

log = structlog.get_logger(__name__)

# ── OpenTelemetry setup (lazy, optional) ────────────────────────────────────

_tracer = None
_initialized = False


def _init_tracer():
    """Initialize OpenTelemetry tracer if SDK is available."""
    global _tracer, _initialized
    if _initialized:
        return _tracer
    _initialized = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": "newsleader-radio"})
        provider = TracerProvider(resource=resource)

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            # Export to OTLP collector (Jaeger, Grafana Tempo, etc.)
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("otel_tracing_enabled", endpoint=endpoint)
        else:
            # No endpoint — use console exporter in development
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            log.info("otel_tracing_console_mode")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("newsleader")

    except ImportError:
        log.info("otel_not_installed: install opentelemetry-sdk to enable tracing")
        _tracer = None

    return _tracer


# ── Tracing context managers ─────────────────────────────────────────────────

@contextlib.contextmanager
def span(name: str, **attributes):
    """
    Context manager for a trace span.
    No-op if OpenTelemetry is not installed.

    Usage:
        with tracing.span("pipeline.run", article_count=5):
            ...pipeline code...
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return

    try:
        from opentelemetry import trace as otel_trace
        with tracer.start_as_current_span(name) as sp:
            for k, v in attributes.items():
                sp.set_attribute(k, str(v))
            t0 = time.monotonic()
            try:
                yield sp
            except Exception as exc:
                sp.record_exception(exc)
                sp.set_status(otel_trace.StatusCode.ERROR, str(exc))
                raise
            finally:
                elapsed_ms = round((time.monotonic() - t0) * 1000)
                sp.set_attribute("duration_ms", elapsed_ms)
    except ImportError:
        yield None


