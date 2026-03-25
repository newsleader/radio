"""
Fallback audio library — keeps the stream alive when LLM/TTS fails.

Strategy (in priority order):
  1. TTS-generated static segments (loaded from disk cache or generated at startup)
  2. Silence (absolute last resort — stream stays connected but silent)

Static segments are TTS-generated Korean announcements:
  - 잠시 후 계속 (brief pause announcement)
  - 뉴스 연결 중 (connecting to news)
  - 잠시 대기 (please wait)
  - 시간 고지 (current time)

Segments are persisted to cache/fallback/N.mp3 (subdirectory, not cache root)
so they load instantly on restart (no TTS call needed) and are NOT picked up by
restore_recent_cache (which globs cache/*.mp3 only).
On first run or if cache files are missing, TTS generates them.
On recovery (real content available again), fallback is skipped.
"""
import asyncio
import threading
from pathlib import Path
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


def _cache_path(idx: int) -> Path:
    from config import config
    # Subdirectory keeps fallback files out of the cache root (restore_recent_cache globs cache/*.mp3)
    return Path(config.CACHE_DIR) / "fallback" / f"{idx}.mp3"


def _load_from_disk() -> list[bytes]:
    """Load pre-generated fallback segments from disk cache."""
    pool = []
    for i in range(len(_FALLBACK_SCRIPTS)):
        p = _cache_path(i)
        if p.exists():
            try:
                data = p.read_bytes()
                if data:
                    pool.append(data)
            except Exception:
                pass
    return pool


def _generate_pool() -> None:
    """Load fallback MP3 segments from disk cache; generate via TTS if missing."""
    from pipeline.tts_engine import text_to_mp3

    # Try loading from disk first (instant, no TTS call needed on restart)
    pool = _load_from_disk()
    if len(pool) == len(_FALLBACK_SCRIPTS):
        with _pool_lock:
            _fallback_pool.extend(pool)
        log.info("fallback_library_ready", segments=len(pool), source="disk_cache")
        return

    # Missing or incomplete cache — generate via TTS and save to disk
    pool = []
    for i, script in enumerate(_FALLBACK_SCRIPTS):
        try:
            mp3 = asyncio.run(text_to_mp3(script))
            if mp3:
                pool.append(mp3)
                log.debug("fallback_segment_generated", bytes=len(mp3))
                # Persist to disk for fast reload on next restart
                try:
                    p = _cache_path(i)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(mp3)
                except Exception as exc:
                    log.debug("fallback_cache_write_failed", error=str(exc))
        except Exception as exc:
            log.warning("fallback_segment_failed", error=str(exc))

    with _pool_lock:
        _fallback_pool.extend(pool)

    log.info("fallback_library_ready", segments=len(pool), source="tts_generated")


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
