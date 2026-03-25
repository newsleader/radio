"""
Korean TTS engine — edge-tts with professional broadcast audio processing.

Audio chain (2-pass):
  1. edge-tts → raw MP3
  2. ffmpeg pass 1: measure loudness (loudnorm JSON)
  3. ffmpeg pass 2:
       highpass=80Hz → mud cut @200Hz → presence @2.5kHz → air @6kHz →
       broadcast compressor → true-peak limiter → loudnorm (linear, measured)
  Fallback: single-pass loudnorm if measurement fails
"""
import asyncio
import html
import itertools
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import edge_tts
import structlog

from config import config
from monitoring.health import increment as _inc

log = structlog.get_logger(__name__)

_voice_cycle = itertools.cycle(config.TTS_VOICES)


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    """Strip URLs, HTML/XML tags, parenthetical English, and non-speech artifacts."""
    text = re.sub(r'https?://\S+|ftp://\S+', '', text)
    text = re.sub(r'<[^>]+/?>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'[<>]', '', text)
    text = re.sub(r'\(([A-Za-z0-9\-\.&/ ]{1,20})\)', '', text)
    text = re.sub(r'[*_`#~]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ── 한국어 TTS 전처리 ──────────────────────────────────────────────────────────

_ACRONYM_MAP = {
    # 경제/금융
    'GDP': '국내총생산', 'GNP': '국민총생산', 'CPI': '소비자물가지수',
    'PPI': '생산자물가지수', 'PCE': '개인소비지출', 'PMI': '구매관리자지수',
    'IMF': '국제통화기금', 'WTO': '세계무역기구', 'OECD': '경제협력개발기구',
    'BIS': '국제결제은행', 'ECB': '유럽중앙은행', 'BOK': '한국은행',
    'SEC': '증권거래위원회', 'IPO': '기업공개', 'ETF': '상장지수펀드',
    # 지정학
    'UN': '유엔', 'NATO': '나토', 'WHO': '세계보건기구',
    'WFP': '세계식량계획', 'IAEA': '국제원자력기구',
    # 기술
    'ML': '머신러닝', 'API': '에이피아이',
    'GPU': '지피유', 'CPU': '씨피유',
}


def _preprocess_for_tts(text: str) -> str:
    """Convert English numbers/units/acronyms to Korean-readable forms."""
    text = re.sub(r'\$(\d+(?:\.\d+)?)\s*[Tt]rillion', lambda m: f"{m.group(1)}조 달러", text)
    text = re.sub(r'\$(\d+(?:\.\d+)?)\s*[Bb]illion', lambda m: f"{m.group(1)}억 달러", text)
    text = re.sub(r'\$(\d+(?:\.\d+)?)\s*[Mm]illion', lambda m: f"{m.group(1)}백만 달러", text)
    text = re.sub(r'\$(\d+(?:,\d+)*(?:\.\d+)?)', lambda m: f"{m.group(1)}달러", text)
    text = re.sub(r'€(\d+(?:\.\d+)?)', lambda m: f"{m.group(1)}유로", text)
    text = re.sub(r'£(\d+(?:\.\d+)?)', lambda m: f"{m.group(1)}파운드", text)
    text = re.sub(r'¥(\d+(?:\.\d+)?)', lambda m: f"{m.group(1)}엔", text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*km\b', lambda m: f"{m.group(1)}킬로미터", text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*kg\b', lambda m: f"{m.group(1)}킬로그램", text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*MW\b', lambda m: f"{m.group(1)}메가와트", text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*GW\b', lambda m: f"{m.group(1)}기가와트", text)
    for abbr, korean in _ACRONYM_MAP.items():
        text = re.sub(rf'\b{re.escape(abbr)}\b', korean, text)
    return text


# ── TTS synthesis ─────────────────────────────────────────────────────────────

async def _synthesize(text: str, voice: str, output_path: str) -> bool:
    """Synthesize Korean text via edge-tts. Retries up to 3 times on truncation."""
    min_bytes = max(30_000, len(text) * 40)

    for attempt in range(3):
        try:
            await edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=config.TTS_RATE,
                volume=config.TTS_VOLUME,
            ).save(output_path)
        except Exception as exc:
            _inc("tts_errors")
            log.error("tts_synthesis_failed", voice=voice, error=str(exc), attempt=attempt + 1)
            if attempt < 2:
                continue
            return False

        actual = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        if actual >= min_bytes:
            return True
        log.warning("tts_output_truncated", voice=voice, actual_bytes=actual,
                    min_bytes=min_bytes, attempt=attempt + 1)
        if attempt < 2:
            await asyncio.sleep(1)

    return False


# ── Audio processing (2-pass loudnorm) ────────────────────────────────────────

_BASE_FILTERS = (
    "highpass=f=80,"
    "equalizer=f=200:width_type=o:width=1.0:g=-3,"
    "equalizer=f=2500:width_type=o:width=1.0:g=2.5,"
    "equalizer=f=6000:width_type=o:width=1.5:g=1.5,"
    "acompressor=threshold=0.125:ratio=3:attack=5:release=80:makeup=2,"
    "alimiter=limit=0.891:level=false"
)

_LOUDNORM_TARGET = "loudnorm=I=-16:TP=-1.5:LRA=11"


def _measure_loudness(src: str) -> Optional[dict]:
    """Pass 1: measure loudness parameters."""
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-af", f"{_BASE_FILTERS},{_LOUDNORM_TARGET}:print_format=json",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        stderr = result.stderr.decode("utf-8", errors="replace")
        m = re.search(r'\{[^{}]+\}', stderr, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as exc:
        log.debug("loudnorm_measure_failed", error=str(exc))
    return None


def _ffmpeg_normalize(src: str, dst: str) -> bool:
    """2-pass broadcast normalization. Falls back to single-pass if measurement fails."""
    measured = _measure_loudness(src)

    if measured:
        try:
            loudnorm = (
                f"{_LOUDNORM_TARGET}"
                f":measured_I={measured['input_i']}"
                f":measured_LRA={measured['input_lra']}"
                f":measured_TP={measured['input_tp']}"
                f":measured_thresh={measured['input_thresh']}"
                f":offset={measured.get('target_offset', '0.0')}"
                ":linear=true"
            )
        except (KeyError, TypeError):
            loudnorm = _LOUDNORM_TARGET
    else:
        loudnorm = _LOUDNORM_TARGET

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-af", f"{_BASE_FILTERS},{loudnorm}",
        "-ar", str(config.SAMPLE_RATE),
        "-ac", str(config.CHANNELS),
        "-b:a", f"{config.MP3_BITRATE}k",
        "-f", "mp3", dst,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0:
            log.warning("ffmpeg_error", stderr=r.stderr.decode()[:400])
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("ffmpeg_timeout")
        return False
    except FileNotFoundError:
        log.error("ffmpeg_not_found")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

async def text_to_mp3(text: str, cache_key: Optional[str] = None) -> Optional[bytes]:
    """Convert Korean text to normalized 128kbps mono MP3 bytes."""
    if cache_key:
        cache_dir = Path(config.CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{cache_key}.mp3"
        if cached.exists():
            log.debug("tts_cache_hit", key=cache_key)
            return cached.read_bytes()

    clean = _clean_for_tts(text)
    clean = _preprocess_for_tts(clean)
    if len(clean) < 10:
        log.warning("tts_text_too_short", original_len=len(text))
        return None

    voice = next(_voice_cycle)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw.mp3")
        norm = os.path.join(tmp, "norm.mp3")

        if not await _synthesize(clean, voice, raw):
            alt = next(_voice_cycle)
            if not await _synthesize(clean, alt, raw):
                log.error("tts_all_voices_failed")
                return None
            voice = alt

        mp3 = Path(norm if _ffmpeg_normalize(raw, norm) else raw).read_bytes()

    if cache_key and mp3:
        (Path(config.CACHE_DIR) / f"{cache_key}.mp3").write_bytes(mp3)

    _inc("tts_completed")
    log.info("tts_complete", voice=voice, bytes=len(mp3))
    return mp3
