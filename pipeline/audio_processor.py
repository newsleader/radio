"""
MP3 frame utilities.

- Splits MP3 bytes into broadcast-sized chunks
- Calculates estimated audio duration from MP3 bytes
- Provides valid silent MP3 for stream keepalive
"""
import os
import subprocess
import tempfile
from pathlib import Path

import structlog

from config import config

log = structlog.get_logger(__name__)

# Lazy-initialized silence cache
_silence_mp3: bytes = b""


def _build_silence_mp3() -> bytes:
    """Generate 1 second of silent MP3 using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=r={config.SAMPLE_RATE}:cl=mono",
                "-t", "1",
                "-b:a", f"{config.MP3_BITRATE}k",
                "-ac", str(config.CHANNELS),
                "-ar", str(config.SAMPLE_RATE),
                "-f", "mp3",
                path,
            ],
            check=True,
            capture_output=True,
        )
        return Path(path).read_bytes()
    except Exception as exc:
        log.warning("silence_build_fallback", error=str(exc))
        # Hard-coded fallback: valid MPEG1 Layer3 128kbps 44100Hz mono silent frame
        # Header: sync=0xFFE0-FFFF, MPEG1, Layer3, 128kbps, 44100Hz, no padding, mono
        frame = b"\xff\xfb\x90\xc4" + b"\x00" * 413  # 417 bytes ≈ 26ms
        return frame * 40  # ~1 second
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def get_silence_mp3() -> bytes:
    """Return a 1-second silent MP3 clip (lazy-initialized, cached)."""
    global _silence_mp3
    if not _silence_mp3:
        _silence_mp3 = _build_silence_mp3()
    return _silence_mp3


def mp3_to_chunks(mp3_bytes: bytes, chunk_size: int = None) -> list[bytes]:
    """Split MP3 bytes into fixed-size chunks for broadcasting."""
    if chunk_size is None:
        chunk_size = config.CHUNK_SIZE
    chunks = []
    offset = 0
    while offset < len(mp3_bytes):
        chunk = mp3_bytes[offset:offset + chunk_size]
        if chunk:
            chunks.append(chunk)
        offset += chunk_size
    return chunks


def estimate_duration_seconds(mp3_bytes: bytes) -> float:
    """Estimate playback duration from MP3 size at configured bitrate."""
    # bitrate is in kbps: bytes / (kbps * 1000 / 8) = seconds
    bytes_per_second = (config.MP3_BITRATE * 1000) / 8
    return len(mp3_bytes) / bytes_per_second
