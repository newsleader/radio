"""
Multi-client thread-safe MP3 fanout broadcaster.

Improvements:
  - ICY metadata injection: injects current news title every ICY_METAINT bytes
  - update_metadata() called by PlaybackLoop when article changes
  - stream_client() supports want_metadata flag from server
"""
import queue
import threading
import time
from typing import Dict, Iterator

import structlog

from config import config
from monitoring.health import increment

log = structlog.get_logger(__name__)

# Valid MPEG1 Layer3 128kbps 44100Hz mono silent frame
_SILENT_FRAME = b"\xff\xfb\x90\xc4" + b"\x00" * 413
_SILENCE_100MS = _SILENT_FRAME * 4   # ~104ms

# ICY metadata injection interval (bytes)
ICY_METAINT = 16000


def _build_icy_metadata(title: str) -> bytes:
    """
    Build ICY metadata block: 1-byte count + N*16 bytes of padded ASCII.
    Format: StreamTitle='...'; padded with null bytes to 16-byte boundary.
    """
    # Truncate and sanitize title (ICY only supports ASCII in most players)
    safe_title = title.encode("ascii", errors="replace").decode("ascii")[:100]
    meta_str = f"StreamTitle='{safe_title}';"
    meta_bytes = meta_str.encode("latin-1", errors="replace")
    # Round up to nearest 16 bytes
    block_count = (len(meta_bytes) + 15) // 16
    padded = meta_bytes.ljust(block_count * 16, b"\x00")
    return bytes([block_count]) + padded


class Broadcaster:
    """Fans out MP3 chunks to all connected HTTP clients."""

    # Disconnect a client after this many consecutive full-queue drops
    _MAX_CONSECUTIVE_DROPS = 50

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: Dict[int, queue.Queue] = {}
        self._drop_counts: Dict[int, int] = {}   # consecutive drop counter per client
        self._next_id = 0
        self._silence = _SILENCE_100MS
        self._current_title: str = "NewsLeader Radio"

    # ── Client management ────────────────────────────────────────────────────

    def add_listener(self) -> tuple[int, queue.Queue]:
        """Register a new streaming client. Returns (client_id, queue)."""
        q: queue.Queue = queue.Queue(maxsize=config.CLIENT_QUEUE_MAXSIZE)
        with self._lock:
            cid = self._next_id
            self._next_id += 1
            self._clients[cid] = q
        log.info("client_connected", client_id=cid, total=self.listener_count)
        return cid, q

    def remove_listener(self, client_id: int) -> None:
        with self._lock:
            self._clients.pop(client_id, None)
            self._drop_counts.pop(client_id, None)
        log.info("client_disconnected", client_id=client_id, total=self.listener_count)

    @property
    def listener_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ── ICY metadata ─────────────────────────────────────────────────────────

    def update_metadata(self, title: str) -> None:
        """Update current title for ICY metadata injection."""
        with self._lock:
            self._current_title = title
        log.info("icy_metadata_updated", title=title[:60])

    @property
    def current_title(self) -> str:
        with self._lock:
            return self._current_title

    # ── Broadcasting ─────────────────────────────────────────────────────────

    def broadcast(self, chunk: bytes) -> None:
        """
        Push chunk to all connected clients (non-blocking, drop on full).
        Clients with too many consecutive drops are forcibly disconnected
        (e.g. sleeping browser tab that has stopped reading the stream).
        """
        with self._lock:
            clients = list(self._clients.items())   # [(cid, queue), ...]

        to_remove = []
        for cid, q in clients:
            try:
                q.put_nowait(chunk)
                # Successful write — reset consecutive drop counter
                with self._lock:
                    self._drop_counts[cid] = 0
            except queue.Full:
                increment("chunks_dropped")
                with self._lock:
                    self._drop_counts[cid] = self._drop_counts.get(cid, 0) + 1
                    drops = self._drop_counts[cid]
                if drops >= self._MAX_CONSECUTIVE_DROPS:
                    log.warning("client_unresponsive_disconnecting",
                                client_id=cid, consecutive_drops=drops)
                    to_remove.append(cid)

        for cid in to_remove:
            self.remove_listener(cid)

    def stream_client(
        self, client_id: int, q: queue.Queue, want_metadata: bool = False
    ) -> Iterator[bytes]:
        """
        Generator that yields MP3 bytes for a single client.

        If want_metadata=True: injects ICY metadata block every ICY_METAINT bytes.
        If want_metadata=False: raw MP3 stream (VLC, ffmpeg, most players).
        """
        byte_offset = 0
        last_title = ""

        try:
            while True:
                try:
                    chunk = q.get(timeout=0.2)
                except queue.Empty:
                    chunk = self._silence

                if not want_metadata:
                    yield chunk
                    continue

                # ICY metadata injection: split chunk at metaint boundaries
                pos = 0
                while pos < len(chunk):
                    space = ICY_METAINT - (byte_offset % ICY_METAINT)
                    piece = chunk[pos:pos + space]
                    yield piece
                    byte_offset += len(piece)
                    pos += len(piece)

                    if byte_offset % ICY_METAINT == 0:
                        # Inject metadata block
                        title = self.current_title
                        if title != last_title:
                            last_title = title
                        yield _build_icy_metadata(last_title)

        except GeneratorExit:
            pass
        finally:
            self.remove_listener(client_id)


# Global singleton
broadcaster = Broadcaster()
