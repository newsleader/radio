"""
Audio queue + real-time pacing loop.

Improvements:
  - Drift-compensating clock (wall-clock anchor prevents accumulated jitter)
  - AudioQueue.enqueue() accepts title for ICY metadata
  - AudioQueue.restore_from_cache() re-loads recent MP3s on restart
  - AudioQueue.enqueue_priority() inserts at front for breaking news
"""
import queue
import threading
import time
from pathlib import Path
from typing import Optional

import structlog

from config import config
from pipeline.audio_processor import mp3_to_chunks, estimate_duration_seconds, get_silence_mp3
from streaming.broadcaster import broadcaster

log = structlog.get_logger(__name__)


class AudioQueue:
    """Thread-safe queue of MP3 chunks with duration tracking."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._total_seconds: float = 0.0
        self._current_title: str = "NewsLeader Radio"

    def enqueue(self, mp3_bytes: bytes, title: str = "") -> None:
        """Add MP3 audio to the play queue (append to end)."""
        duration = estimate_duration_seconds(mp3_bytes)
        chunks = mp3_to_chunks(mp3_bytes)
        for chunk in chunks:
            self._q.put(chunk)
        with self._lock:
            self._total_seconds += duration
            if title:
                self._current_title = title
        log.info("audio_enqueued",
                 duration_s=round(duration, 1),
                 queue_s=round(self.buffered_seconds, 1),
                 title=title[:60] if title else "")

    def enqueue_priority(self, mp3_bytes: bytes, title: str = "") -> None:
        """Insert MP3 at front of queue (breaking news)."""
        duration = estimate_duration_seconds(mp3_bytes)
        new_chunks = mp3_to_chunks(mp3_bytes)
        with self._lock:
            existing = []
            while True:
                try:
                    existing.append(self._q.get_nowait())
                except queue.Empty:
                    break
            for chunk in new_chunks:
                self._q.put(chunk)
            for chunk in existing:
                self._q.put(chunk)
            self._total_seconds += duration
            if title:
                self._current_title = title
        log.info("audio_enqueued_priority",
                 duration_s=round(duration, 1),
                 queue_s=round(self.buffered_seconds, 1),
                 title=title[:60] if title else "")

    def restore_from_cache(self, cache_dir: str, max_age_hours: int = 2) -> int:
        """Re-enqueue recent MP3s from cache after restart."""
        from storage.article_store import article_store
        files = article_store.restore_recent_cache(cache_dir, max_age_hours)
        files = files[-10:]  # cap at 10
        count = 0
        for mp3_path, _ in files:
            try:
                mp3_bytes = Path(mp3_path).read_bytes()
                if len(mp3_bytes) > 1000:
                    self.enqueue(mp3_bytes, title="NewsLeader Radio")
                    count += 1
            except Exception as exc:
                log.warning("cache_restore_error", file=str(mp3_path), error=str(exc))
        if count:
            log.info("cache_restored", files=count,
                     queue_s=round(self.buffered_seconds, 1))
        return count

    def get_chunk(self) -> Optional[bytes]:
        """Get next chunk; returns None if queue is empty."""
        try:
            chunk = self._q.get_nowait()
            with self._lock:
                bps = (config.MP3_BITRATE * 1000) / 8
                self._total_seconds -= max(0, len(chunk) / bps)
                self._total_seconds = max(0.0, self._total_seconds)
            return chunk
        except queue.Empty:
            return None

    @property
    def buffered_seconds(self) -> float:
        with self._lock:
            return self._total_seconds

    @property
    def current_title(self) -> str:
        with self._lock:
            return self._current_title

    def is_critical(self) -> bool:
        return self.buffered_seconds < config.BUFFER_CRITICAL

    def is_low(self) -> bool:
        return self.buffered_seconds < config.BUFFER_LOW

    def is_full(self) -> bool:
        return self.buffered_seconds >= config.BUFFER_FULL

    def watermark_status(self) -> str:
        """Return buffer watermark level: 'critical' | 'low' | 'ok' | 'full'."""
        s = self.buffered_seconds
        if s < config.BUFFER_CRITICAL:
            return "critical"
        if s < config.BUFFER_LOW:
            return "low"
        if s >= config.BUFFER_FULL:
            return "full"
        return "ok"


# Global singleton
audio_queue = AudioQueue()


class PlaybackLoop:
    """
    Continuously reads from AudioQueue and broadcasts to all clients.

    Wall-clock anchor prevents accumulated drift:
    each chunk's target time is anchored to an absolute start,
    so one slow iteration doesn't permanently shift the clock.
    """

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._silence_pool: bytes = b""
        self._silence_offset: int = 0
        self._last_title: str = ""

    def _get_silence_chunk(self) -> bytes:
        chunk_size = config.CHUNK_SIZE
        if len(self._silence_pool) < chunk_size * 2:
            base = get_silence_mp3()
            while len(base) < chunk_size * 4:
                base += get_silence_mp3()
            self._silence_pool = base
        pool_len = len(self._silence_pool)
        start = self._silence_offset % pool_len
        end = start + chunk_size
        if end <= pool_len:
            chunk = self._silence_pool[start:end]
        else:
            chunk = self._silence_pool[start:] + self._silence_pool[:end - pool_len]
        self._silence_offset = (self._silence_offset + chunk_size) % pool_len
        return chunk

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="playback-loop"
        )
        self._thread.start()
        log.info("playback_loop_started")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        bps = (config.MP3_BITRATE * 1000) / 8   # 16000 bytes/sec at 128kbps
        chunk_size = config.CHUNK_SIZE
        interval = chunk_size / bps              # 0.128s per chunk

        start_time = time.monotonic()
        n = 0

        while self._running:
            chunk = audio_queue.get_chunk()
            if chunk is None:
                chunk = self._get_silence_chunk()

            # Propagate title changes to broadcaster for ICY metadata
            title = audio_queue.current_title
            if title != self._last_title:
                broadcaster.update_metadata(title)
                self._last_title = title

            broadcaster.broadcast(chunk)

            # Drift-compensating sleep
            n += 1
            target = start_time + n * interval
            wait = target - time.monotonic()
            if wait > 0.001:
                time.sleep(wait)
            # If wait <= 0: we're behind, don't sleep — catch up


# Global singleton
playback_loop = PlaybackLoop()
