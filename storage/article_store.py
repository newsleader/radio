"""
SQLite-backed article deduplication store.

Extended schema:
  seen_articles — URL hash + SimHash + title hash + embedding tokens + metadata
  feed_state    — ETag/Last-Modified/health tracking per feed URL
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

from config import config

log = structlog.get_logger(__name__)

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "fbclid", "gclid", "_ga", "mc_cid", "mc_eid",
})


def normalize_url(url: str) -> str:
    """Strip tracking parameters and normalize scheme."""
    from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
    try:
        parsed = urlparse(url.lower().strip())
        params = {k: v for k, v in parse_qs(parsed.query).items()
                  if k not in _TRACKING_PARAMS}
        normalized = parsed._replace(
            scheme="https",
            query=urlencode(sorted(params.items()), doseq=True),
            fragment="",
        )
        return urlunparse(normalized)
    except Exception:
        return url


def compute_simhash(title: str, body_prefix: str = "") -> int:
    """Compute 64-bit SimHash of title + first 200 chars of body."""
    try:
        from simhash import Simhash
        text = (title + " " + body_prefix[:200]).lower()
        return Simhash(text).value
    except ImportError:
        # Fallback: use simple hash if simhash not installed
        text = (title + " " + body_prefix[:200]).lower()
        return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def _normalize_title(title: str) -> str:
    """Normalize title for hash comparison (remove punctuation, lowercase)."""
    return re.sub(r'[^\w\s]', '', title.lower().strip())


class ArticleStore:
    """Thread-safe SQLite store for seen articles and feed state."""

    def __init__(self, db_path: str = None) -> None:
        self._db_path = db_path or config.DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")  # 32MB page cache
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()

            # Original table (keep for backward compat)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_articles (
                    url_hash     TEXT PRIMARY KEY,
                    seen_at      TEXT NOT NULL
                )
            """)

            # Add extended columns if they don't exist (idempotent)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(seen_articles)")}
            for col, typedef in [
                ("title_hash",    "TEXT"),
                ("simhash",       "INTEGER"),
                ("source",        "TEXT"),
                ("quality_score", "REAL DEFAULT 0.5"),
                ("aired",         "INTEGER DEFAULT 0"),
                ("embed_tokens",  "TEXT"),   # JSON dict of {token: weight}
            ]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE seen_articles ADD COLUMN {col} {typedef}")

            # Indexes for fast lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_at ON seen_articles(seen_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_simhash  ON seen_articles(simhash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_title_hash ON seen_articles(title_hash)")

            # Feed health tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feed_state (
                    feed_url              TEXT PRIMARY KEY,
                    etag                  TEXT,
                    last_modified         TEXT,
                    last_success_at       TEXT,
                    consecutive_failures  INTEGER DEFAULT 0,
                    next_check_at         TEXT,
                    avg_latency_ms        REAL DEFAULT 0
                )
            """)

            conn.commit()
            conn.close()
        log.info("article_store_initialized", path=self._db_path)

    # ── Article deduplication ────────────────────────────────────────────────

    def seen(self, url_hash: str) -> bool:
        """Return True if URL hash has been seen within TTL window."""
        cutoff = (datetime.utcnow() - timedelta(days=config.ARTICLE_TTL_DAYS)).isoformat()
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT 1 FROM seen_articles WHERE url_hash=? AND seen_at>?",
                (url_hash, cutoff),
            ).fetchone()
            conn.close()
        return row is not None

    def seen_simhash(self, simhash_value: int, threshold: int = 3) -> bool:
        """
        Return True if a near-duplicate article (same SimHash ±threshold bits) exists.
        Hamming distance ≤ threshold → near-duplicate.
        """
        if simhash_value == 0:
            return False
        cutoff = (datetime.utcnow() - timedelta(days=config.ARTICLE_TTL_DAYS)).isoformat()
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT simhash FROM seen_articles WHERE simhash IS NOT NULL AND seen_at>?",
                (cutoff,),
            ).fetchall()
            conn.close()

        for (existing,) in rows:
            if existing is None:
                continue
            diff = bin(simhash_value ^ existing).count("1")
            if diff <= threshold:
                return True
        return False

    def seen_title_hash(self, title_hash: str) -> bool:
        """Return True if an article with this normalized title hash was seen recently."""
        cutoff = (datetime.utcnow() - timedelta(days=config.ARTICLE_TTL_DAYS)).isoformat()
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT 1 FROM seen_articles WHERE title_hash=? AND seen_at>?",
                (title_hash, cutoff),
            ).fetchone()
            conn.close()
        return row is not None

    def mark_seen(self, url_hash: str, title: str = "", source: str = "",
                  simhash_value: int = 0, quality_score: float = 0.5,
                  embed_tokens: Optional[dict] = None) -> None:
        """Mark a URL hash as seen with optional metadata and embedding tokens."""
        now = datetime.utcnow().isoformat()
        title_hash = hashlib.sha256(_normalize_title(title).encode()).hexdigest() if title else None
        embed_json = json.dumps(embed_tokens, ensure_ascii=False) if embed_tokens else None
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT OR REPLACE INTO seen_articles
                   (url_hash, seen_at, title_hash, simhash, source, quality_score, embed_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (url_hash, now, title_hash,
                 simhash_value if simhash_value else None,
                 source or None, quality_score, embed_json),
            )
            conn.commit()
            conn.close()

    def seen_embedding(self, embed_vec: dict, threshold: float = 0.65) -> bool:
        """
        Return True if a cross-language near-duplicate exists based on
        embedding cosine similarity ≥ threshold.
        Only checks articles from the last ARTICLE_TTL_DAYS.
        """
        if not embed_vec:
            return False
        from pipeline.embedder import cosine_similarity
        cutoff = (datetime.utcnow() - timedelta(days=config.ARTICLE_TTL_DAYS)).isoformat()
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT embed_tokens FROM seen_articles "
                "WHERE embed_tokens IS NOT NULL AND seen_at>?",
                (cutoff,),
            ).fetchall()
            conn.close()

        for (tok_json,) in rows:
            try:
                stored_vec = json.loads(tok_json)
                if cosine_similarity(embed_vec, stored_vec) >= threshold:
                    return True
            except Exception:
                continue
        return False

    def cleanup_expired(self) -> int:
        """Remove entries older than ARTICLE_TTL_DAYS. Returns deleted count."""
        cutoff = (datetime.utcnow() - timedelta(days=config.ARTICLE_TTL_DAYS)).isoformat()
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "DELETE FROM seen_articles WHERE seen_at<=?", (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
        if deleted:
            log.info("article_store_cleanup", deleted=deleted)
        return deleted

    # ── Feed state (ETag / health) ───────────────────────────────────────────

    def get_feed_state(self, feed_url: str) -> Optional[dict]:
        """Return feed state dict or None if not found."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT etag, last_modified, last_success_at, "
                "consecutive_failures, next_check_at, avg_latency_ms "
                "FROM feed_state WHERE feed_url=?",
                (feed_url,),
            ).fetchone()
            conn.close()
        if row is None:
            return None
        return {
            "etag": row[0],
            "last_modified": row[1],
            "last_success_at": row[2],
            "consecutive_failures": row[3] or 0,
            "next_check_at": row[4],
            "avg_latency_ms": row[5] or 0.0,
        }

    def update_feed_state(self, feed_url: str, **kwargs) -> None:
        """Upsert feed state fields."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            conn = self._connect()
            existing = conn.execute(
                "SELECT feed_url FROM feed_state WHERE feed_url=?", (feed_url,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO feed_state (feed_url) VALUES (?)", (feed_url,)
                )
            updates = {k: v for k, v in kwargs.items()
                       if k in ("etag", "last_modified", "last_success_at",
                                "consecutive_failures", "next_check_at", "avg_latency_ms")}
            if updates:
                set_clause = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE feed_state SET {set_clause} WHERE feed_url=?",
                    (*updates.values(), feed_url),
                )
            conn.commit()
            conn.close()

    def should_check_feed(self, feed_url: str) -> bool:
        """Return False if feed is in exponential backoff window."""
        state = self.get_feed_state(feed_url)
        if state is None:
            return True
        next_check = state.get("next_check_at")
        if next_check and datetime.utcnow().isoformat() < next_check:
            return False
        return True

    def record_feed_success(self, feed_url: str, latency_ms: float = 0.0) -> None:
        """Record successful feed fetch, reset failure counter."""
        now = datetime.utcnow().isoformat()
        state = self.get_feed_state(feed_url)
        old_latency = (state or {}).get("avg_latency_ms", 0.0)
        # Exponential moving average
        new_latency = old_latency * 0.8 + latency_ms * 0.2 if old_latency else latency_ms
        self.update_feed_state(
            feed_url,
            last_success_at=now,
            consecutive_failures=0,
            next_check_at=None,
            avg_latency_ms=new_latency,
        )

    def record_feed_failure(self, feed_url: str) -> int:
        """Record failed feed fetch. Returns new failure count."""
        import random
        state = self.get_feed_state(feed_url) or {}
        failures = (state.get("consecutive_failures") or 0) + 1
        # Backoff: 2^failures minutes, capped at 4 hours (240 min), with ±25% jitter
        backoff_min = min(2 ** failures, 240)
        jitter = backoff_min * 0.25 * (random.random() * 2 - 1)  # ±25%
        backoff_min = max(1, backoff_min + jitter)
        next_check = (datetime.utcnow() + timedelta(minutes=backoff_min)).isoformat()
        self.update_feed_state(
            feed_url,
            consecutive_failures=failures,
            next_check_at=next_check,
        )
        return failures

    # ── Cache restore helper ─────────────────────────────────────────────────

    def restore_recent_cache(self, cache_dir: str, max_age_hours: int = 2) -> list:
        """
        Return list of (mp3_path, mtime) for MP3 files generated within
        max_age_hours. Used by AudioQueue to restore content after restart.
        """
        cache_path = Path(cache_dir)
        if not cache_path.exists():
            return []
        cutoff = time.time() - max_age_hours * 3600
        files = [
            (f, f.stat().st_mtime)
            for f in cache_path.glob("*.mp3")
            if f.stat().st_mtime > cutoff
        ]
        files.sort(key=lambda x: x[1])  # oldest first
        return files


# Global singleton
article_store = ArticleStore()
