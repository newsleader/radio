"""
Async RSS fetcher with deduplication and health tracking.

Improvements over baseline:
  - fastfeedparser (25-50x faster than feedparser, same API)
  - URL normalization (strip UTM params) before hashing
  - RSS content:encoded check before HTTP body fetch
  - ETag / If-Modified-Since conditional GET (304 = skip)
  - Per-domain rate limiting (aiolimiter) to avoid IP blocks
  - Feed health tracking with exponential backoff
  - SimHash near-duplicate detection
  - Realistic User-Agent string
"""
import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, List, Optional
from urllib.parse import urlparse

import aiohttp
import structlog

from storage.article_store import article_store, normalize_url, compute_simhash
from pipeline.embedder import embed
from content.feeds import RSS_FEEDS

log = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)    # 24 feeds have avg_latency 15-27s; 15s was too short
ARTICLE_TIMEOUT = aiohttp.ClientTimeout(total=12)  # article body fetch
MAX_ARTICLES_PER_FEED = 8
MAX_ARTICLE_AGE_HOURS = 8
MIN_BODY_LENGTH = 300  # articles shorter than this rarely produce 120-word scripts

# Title patterns that indicate non-news content — filtered before body fetch (saves HTTP round-trip)
_NON_NEWS_TITLE_RE = re.compile(
    r"운세|점성|별자리"                           # horoscope/astrology
    r"|^\S[\w\-\.]+\s+v?\d+\.\d+[a-z]\d*$"      # software release: "package-name 1.2a3"
    r"|demo day dates?"                           # event listing titles
    r"|\bchangelog\b"                             # changelog articles
    r"|【地震情報】"                              # Japanese earthquake alerts (always thin, not Korean news)
    r"|골든크로스|데드크로스",                    # stock technical analysis screener alerts (not radio news)
    re.IGNORECASE,
)

_USER_AGENT = "Mozilla/5.0 (compatible; NewsLeader/1.0; +https://github.com/newsleader)"

# Per-domain rate limiters are created fresh per event-loop invocation (see fetch_new_articles).
# Global dict is intentionally NOT used — AsyncLimiter binds to the event loop it's created on,
# and asyncio.run() creates a new loop each call, causing "re-used across loops" warnings.
try:
    from aiolimiter import AsyncLimiter as _AsyncLimiter
    _HAS_LIMITER = True
except ImportError:
    _HAS_LIMITER = False
    log.warning("aiolimiter_not_installed", msg="per-domain rate limiting disabled")


@dataclass
class Article:
    url: str
    title: str
    source: str
    body: str
    published: Optional[str] = None


# ── Feed parsing ─────────────────────────────────────────────────────────────

def _parse_feed(raw: str):
    """Parse RSS/Atom feed, prefer fastfeedparser then feedparser as fallback."""
    try:
        import fastfeedparser
        return fastfeedparser.parse(raw)
    except ImportError:
        pass
    except Exception:
        pass
    import feedparser
    return feedparser.parse(raw)


# ── Freshness check ──────────────────────────────────────────────────────────

def _is_fresh(entry: Any) -> bool:
    raw = (
        getattr(entry, "published", None)
        or getattr(entry, "updated", None)
        or getattr(entry, "created", None)
    )
    if not raw:
        return True
    try:
        pub = parsedate_to_datetime(raw)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pub) <= timedelta(hours=MAX_ARTICLE_AGE_HOURS)
    except Exception:
        return True


# ── Body extraction ──────────────────────────────────────────────────────────

def _get_content_encoded(entry: Any, url: str = "") -> str:
    """Extract full article text from RSS content:encoded field."""
    content_list = getattr(entry, "content", [])
    if content_list:
        val = content_list[0].get("value", "") if isinstance(content_list[0], dict) \
              else getattr(content_list[0], "value", "")
        if val and len(val) > 200:
            try:
                import trafilatura
                text = trafilatura.extract(val, url=url or None,
                                           include_comments=False, include_tables=False)
                if text and len(text) > 150:
                    return text[:3000]
            except Exception:
                pass
            # Strip HTML tags
            import re
            clean = re.sub(r"<[^>]+>", " ", val)
            clean = re.sub(r"\s+", " ", clean).strip()
            if len(clean) > 150:
                return clean[:3000]
    return ""


async def _extract_body(session: aiohttp.ClientSession, url: str, entry: Any) -> str:
    # 1. Try RSS content:encoded (no HTTP request needed)
    inline = _get_content_encoded(entry, url=url)
    if inline:
        return inline

    # 2. Try HTTP fetch + trafilatura
    try:
        async with session.get(
            url, timeout=ARTICLE_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
            ssl=False,
        ) as resp:
            html = await resp.text(errors="replace")

        import trafilatura
        text = trafilatura.extract(html, url=url,
                                   include_comments=False, include_tables=False)
        if text and len(text) > 150:
            return text[:3000]
    except Exception:
        pass

    # 3. Fallback: RSS summary / description
    summary = (
        getattr(entry, "summary", "")
        or getattr(entry, "description", "")
        or ""
    )
    return summary[:2000]


# ── Single feed fetch ─────────────────────────────────────────────────────────

async def _fetch_feed(
    session: aiohttp.ClientSession,
    feed_url: str,
    source_name: str,
    limiters: dict,
) -> List[Article]:
    """Fetch one RSS feed with conditional GET and health tracking."""
    if not article_store.should_check_feed(feed_url):
        log.debug("feed_backoff_skipped", feed=source_name)
        return []

    state = article_store.get_feed_state(feed_url) or {}
    headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]

    t0 = time.monotonic()
    try:
        domain = urlparse(feed_url).netloc
        # Use per-loop limiters passed in from fetch_new_articles
        if _HAS_LIMITER and domain in limiters:
            async with limiters[domain]:
                async with session.get(
                    feed_url, timeout=FETCH_TIMEOUT, headers=headers, ssl=False
                ) as resp:
                    if resp.status == 304:
                        log.debug("feed_not_modified", feed=source_name)
                        article_store.record_feed_success(feed_url)
                        from monitoring.health import increment as _inc
                        _inc("feed_304s")
                        return []
                    new_etag = resp.headers.get("ETag")
                    new_lm = resp.headers.get("Last-Modified")
                    raw = await resp.text(errors="replace")
        else:
            async with session.get(
                feed_url, timeout=FETCH_TIMEOUT, headers=headers, ssl=False
            ) as resp:
                if resp.status == 304:
                    log.debug("feed_not_modified", feed=source_name)
                    article_store.record_feed_success(feed_url)
                    from monitoring.health import increment as _inc
                    _inc("feed_304s")
                    return []
                new_etag = resp.headers.get("ETag")
                new_lm = resp.headers.get("Last-Modified")
                raw = await resp.text(errors="replace")

    except Exception as exc:
        failures = article_store.record_feed_failure(feed_url)
        log.warning("feed_fetch_error", feed=source_name,
                    error=str(exc) or type(exc).__name__,
                    exc_type=type(exc).__name__,
                    consecutive_failures=failures)
        return []

    latency_ms = (time.monotonic() - t0) * 1000

    # Update ETag / Last-Modified
    update_kwargs = {}
    if new_etag:
        update_kwargs["etag"] = new_etag
    if new_lm:
        update_kwargs["last_modified"] = new_lm
    article_store.record_feed_success(feed_url, latency_ms=latency_ms)
    if update_kwargs:
        article_store.update_feed_state(feed_url, **update_kwargs)

    parsed = _parse_feed(raw)
    articles = []

    for entry in parsed.entries[:MAX_ARTICLES_PER_FEED]:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", "").strip()
        if not url or not title:
            continue

        if not _is_fresh(entry):
            continue

        # Title-based non-news filter (cheap regex, runs before HTTP body fetch)
        if _NON_NEWS_TITLE_RE.search(title):
            log.debug("non_news_title_skipped", title=title[:80])
            from monitoring.health import increment as _inc
            _inc("articles_filtered_title")
            continue

        # URL-hash dedup (exact URL match)
        normalized = normalize_url(url)
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()
        if article_store.seen(url_hash):
            continue

        # Title-hash dedup (same title, different URL)
        title_hash = hashlib.sha256(title.lower().strip().encode()).hexdigest()
        if article_store.seen_title_hash(title_hash):
            continue

        # Body extraction
        body = await _extract_body(session, url, entry)
        if not body or len(body) < MIN_BODY_LENGTH:
            from monitoring.health import increment as _inc
            _inc("articles_filtered_body")
            continue

        # SimHash near-duplicate check
        sim = compute_simhash(title, body)
        if article_store.seen_simhash(sim):
            log.debug("simhash_dup_skipped", title=title[:60])
            continue

        # Cross-language embedding dedup (Korean ↔ English same story)
        embed_vec = embed(title, body)
        if article_store.seen_embedding(embed_vec, threshold=0.65):
            log.debug("embed_dup_skipped", title=title[:60])
            continue

        articles.append(Article(
            url=normalized,
            title=title,
            source=source_name,
            body=body,
            published=getattr(entry, "published", None),
        ))

    return articles


# ── Main fetch function ───────────────────────────────────────────────────────

async def fetch_new_articles() -> List[Article]:
    """Fetch all configured RSS feeds in parallel and return new articles."""
    # Build per-domain limiters fresh for THIS event loop (AsyncLimiter binds to its loop)
    limiters: dict = {}
    if _HAS_LIMITER:
        domains = {urlparse(url).netloc for _, url in RSS_FEEDS}
        for d in domains:
            limiters[d] = _AsyncLimiter(max_rate=1, time_period=2.0)

    connector = aiohttp.TCPConnector(limit=len(RSS_FEEDS), ssl=False)  # 1 slot per feed = 0 pool wait; was 80
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _fetch_feed(session, url, name, limiters)
            for name, url in RSS_FEEDS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    articles: List[Article] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
        elif isinstance(r, Exception):
            log.warning("feed_gather_error", error=str(r))

    log.info("articles_fetched", count=len(articles))
    return articles
