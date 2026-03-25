"""
Fallback audio library — keeps the stream alive when LLM/TTS fails.

Strategy (in priority order):
  1. TTS-generated static segments (generated once at startup, cached)
  2. Silence (absolute last resort — stream stays connected but silent)

Static segments are TTS-generated Korean announcements:
  - 잠시 후 계속 (brief pause announcement)
  - 뉴스 연결 중 (connecting to news)
  - 잠시 대기 (please wait)
  - 시간 고지 (current time)

Each segment is generated at startup and stored in memory.
On recovery (real content available again), fallback is skipped.
"""
import asyncio
import threading
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_FALLBACK_SCRIPTS = [
    "잠시 후 더 많은 소식을 전해드리겠습니다. 뉴스리더 라디오를 계속 청취해 주십시오.",
    "현재 최신 뉴스를 준비하고 있습니다. 잠시만 기다려 주십시오.",
    "글로벌 뉴스를 실시간으로 전달하는 뉴스리더 라디오입니다. 곧 새로운 소식을 전해드리겠습니다.",
    "잠시 후 국내외 최신 소식으로 돌아오겠습니다. 뉴스리더 라디오였습니다.",
]

_fallback_pool: list[bytes] = []   # pre-generated MP3 bytes
_pool_lock = threading.Lock()


def _generate_pool() -> None:
    """Generate fallback MP3 segments at startup (runs in background thread)."""
    from pipeline.tts_engine import text_to_mp3

    pool: list[bytes] = []
    for script in _FALLBACK_SCRIPTS:
        try:
            mp3 = asyncio.run(text_to_mp3(script))
            if mp3:
                pool.append(mp3)
                log.debug("fallback_segment_generated", bytes=len(mp3))
        except Exception as exc:
            log.warning("fallback_segment_failed", error=str(exc))

    with _pool_lock:
        _fallback_pool.extend(pool)

    log.info("fallback_library_ready", segments=len(pool))


def initialize_async() -> None:
    """Start background generation of fallback segments (non-blocking)."""
    t = threading.Thread(target=_generate_pool, daemon=True, name="fallback-gen")
    t.start()


def get_fallback_mp3() -> Optional[bytes]:
    """Return the next fallback MP3 from the pool (round-robin), or None."""
    with _pool_lock:
        if not _fallback_pool:
            return None
        # Pop from front and re-append (round-robin)
        mp3 = _fallback_pool.pop(0)
        _fallback_pool.append(mp3)
        return mp3


def enqueue_fallback(count: int = 1) -> int:
    """
    Enqueue `count` fallback MP3 segments into the audio queue.
    Returns number actually enqueued.
    Called by watchdog when buffer is critical and pipeline is busy.
    """
    from pipeline.queue_manager import audio_queue

    enqueued = 0
    for _ in range(count):
        mp3 = get_fallback_mp3()
        if not mp3:
            break
        audio_queue.enqueue(mp3, title="뉴스리더 라디오 — 잠시 후 계속")
        enqueued += 1

    if enqueued:
        log.info("fallback_enqueued", count=enqueued,
                 queue_s=round(audio_queue.buffered_seconds, 1))
    return enqueued
