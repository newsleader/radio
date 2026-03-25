"""
APScheduler-based content production scheduler.

Jobs:
  - Every 15 min: RSS fetch → script → TTS → queue
  - Every 30 sec: watchdog (emergency fetch if queue < BUFFER_CRITICAL)
  - Every hour :00: station ID broadcast
  - Daily midnight: article_store cleanup

"""
import asyncio
import hashlib
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from pipeline.fetcher import fetch_new_articles
from pipeline.gdelt_fetcher import fetch_gdelt_articles
from pipeline.script_generator import generate_script, generate_station_id
from pipeline.tts_engine import text_to_mp3
from pipeline.queue_manager import audio_queue
from pipeline.editorial import (
    categorize_article, score_article, get_time_weight, mmr_select,
    editorial_scheduler, breaking_detector,
)
from pipeline.embedder import embed as compute_embed
from pipeline.event_clustering import cluster_articles
from pipeline.fallback_library import enqueue_fallback, initialize_async as init_fallback
from storage.article_store import article_store, compute_simhash
from monitoring.health import increment, set_pipeline_run
from monitoring.tracing import span as trace_span

log = structlog.get_logger(__name__)

_pipeline_lock = threading.Lock()


_ARCHIVE_ROOT = Path("archive")
_ARCHIVE_KEEP_DAYS = 7


def _archive_mp3(mp3_bytes: bytes, title: str) -> None:
    """방송된 MP3를 archive/YYYY-MM-DD/HH-MM-SS_title.mp3 로 저장."""
    try:
        now = datetime.now(timezone.utc).astimezone()  # 로컬 시간
        date_dir = _ARCHIVE_ROOT / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        # 파일명: 시간_제목 (파일시스템 안전 문자만)
        safe_title = re.sub(r'[^\w가-힣\- ]', '', title)[:40].strip()
        filename = now.strftime("%H-%M-%S") + "_" + safe_title + ".mp3"
        (date_dir / filename).write_bytes(mp3_bytes)
    except Exception as exc:
        log.debug("archive_save_failed", error=str(exc))


def _cleanup_archive() -> None:
    """7일 이상 된 archive 폴더 삭제."""
    if not _ARCHIVE_ROOT.exists():
        return
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=_ARCHIVE_KEEP_DAYS)
    deleted = 0
    for date_dir in _ARCHIVE_ROOT.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).astimezone()
            if dir_date < cutoff:
                import shutil
                shutil.rmtree(date_dir)
                deleted += 1
        except ValueError:
            pass
    log.info("archive_cleanup", deleted_days=deleted)


def run_content_pipeline(emergency: bool = False) -> None:
    """Full pipeline: RSS → script → TTS → queue."""
    if not _pipeline_lock.acquire(blocking=False):
        log.info("pipeline_skipped", reason="already_running")
        return

    try:
        if audio_queue.is_full() and not emergency:
            log.info("pipeline_skipped", reason="queue_full",
                     buffered_s=audio_queue.buffered_seconds)
            return

        log.info("pipeline_start", emergency=emergency)
        increment("pipeline_runs")

        # Fetch from RSS feeds + GDELT (merged)
        with trace_span("pipeline.fetch"):
            rss_articles = asyncio.run(fetch_new_articles())
            # Skip GDELT when buffer is low OR RSS already gives enough articles
            # GDELT: 5 queries × ~20s = ~100s, consistently returns 0 articles when RSS has 30+
            gdelt_skip = (
                emergency
                or (audio_queue.buffered_seconds < config.BUFFER_LOW)
                or (len(rss_articles) >= 30)
            )
            gdelt_articles = [] if gdelt_skip else asyncio.run(fetch_gdelt_articles())
        articles = rss_articles + gdelt_articles
        increment("articles_fetched", len(articles))

        if not articles:
            log.info("pipeline_no_new_articles")
            set_pipeline_run(success=True)
            return

        # Cluster articles to find cross-feed coverage (boosts important stories)
        clusters = cluster_articles(articles)
        # Build {article_url → cluster_size} for scoring
        cluster_size_map: dict[str, int] = {}
        for cluster in clusters:
            sz = cluster.source_count
            for a in cluster.articles:
                cluster_size_map[a.url] = sz

        # Score articles: base score × time-of-day category weight
        scored_raw = []
        for a in articles:
            cat = categorize_article(a.title, a.source)
            sz = cluster_size_map.get(a.url, 1)
            base = score_article(a, cluster_size=sz)
            tw = get_time_weight(cat)
            scored_raw.append((a, base * tw, cat))

        # MMR selection: top-20 by score, then reorder for diversity
        scored_raw.sort(key=lambda x: x[1], reverse=True)
        top_articles = [x[0] for x in scored_raw[:20]]
        top_scores   = [x[1] for x in scored_raw[:20]]
        ordered = mmr_select(top_articles, top_scores, k=len(top_articles))

        # Build final list with precomputed (article, score, category)
        score_map = {id(x[0]): (x[1], x[2]) for x in scored_raw}
        scored = [(a, *score_map[id(a)]) for a in ordered]

        processed = 0

        for article, art_score, category in scored:
            if audio_queue.is_full():
                log.info("pipeline_queue_full_stopping")
                break

            # Breaking news detection
            is_brk = breaking_detector.check_and_register(article.title, article.source)
            if is_brk:
                increment("breaking_news")

            # Editorial diversity check
            if not emergency and not editorial_scheduler.should_broadcast(category, is_breaking_news=is_brk):
                log.debug("editorial_skipped",
                          category=category, title=article.title[:50])
                continue

            try:
                result = generate_script(article)
            except Exception as exc:
                log.warning("script_skipped",
                            title=article.title[:60], error=type(exc).__name__)
                continue
            if not result:
                continue
            script, topic = result

            cache_key = hashlib.sha256(script.encode()).hexdigest()[:16]
            mp3_bytes = asyncio.run(text_to_mp3(script, cache_key=cache_key))
            if not mp3_bytes:
                continue

            # Use Korean topic as display title if available (fallback: English article title)
            display_title = topic or article.title
            if is_brk:
                audio_queue.enqueue_priority(mp3_bytes, title=display_title)
            else:
                audio_queue.enqueue(mp3_bytes, title=display_title)

            # ── Archive: 날짜별 MP3 저장 ──────────────────────────
            _archive_mp3(mp3_bytes, article.title)

            editorial_scheduler.record_broadcast(category)

            url_hash = hashlib.sha256(article.url.encode()).hexdigest()
            embed_vec = compute_embed(article.title, article.body)
            article_store.mark_seen(
                url_hash,
                title=article.title,
                source=article.source,
                simhash_value=compute_simhash(article.title, article.body[:600]),
                quality_score=min(art_score / 10.0, 1.0),
                embed_tokens=embed_vec,
                aired=True,
            )
            processed += 1

        log.info("pipeline_complete", processed=processed,
                 queue_s=round(audio_queue.buffered_seconds, 1))
        set_pipeline_run(success=True)

    except Exception as exc:
        log.error("pipeline_error", error=str(exc), exc_info=True)
        set_pipeline_run(success=False)
    finally:
        _pipeline_lock.release()


def run_watchdog() -> None:
    """
    Buffer watermark watchdog — 3 stages:
      critical (< 60s)  → enqueue fallback audio immediately + run pipeline
      low      (< 180s) → run pipeline soon (emergency)
      ok / full         → no action
    """
    status = audio_queue.watermark_status()
    buffered = audio_queue.buffered_seconds
    if status == "critical":
        log.warning("watchdog_critical", buffered_s=round(buffered, 1))
        # Enqueue fallback immediately to prevent silence, then run pipeline
        # count=4: all 4 scripts (~40s) covers the gap until next pipeline article
        enqueue_fallback(count=4)
        run_content_pipeline(emergency=True)
    elif status == "low":
        log.warning("watchdog_low", buffered_s=round(buffered, 1))
        run_content_pipeline(emergency=True)
    else:
        log.debug("watchdog_ok", status=status, buffered_s=round(buffered, 1))


def run_station_id() -> None:
    """Broadcast a station identification message."""
    log.info("station_id_broadcast")
    script = generate_station_id()
    mp3_bytes = asyncio.run(text_to_mp3(script))
    if mp3_bytes:
        audio_queue.enqueue(mp3_bytes, title="뉴스리더 라디오 스테이션 ID")


def run_daily_cleanup() -> None:
    """Remove expired entries from article store + archive cleanup."""
    deleted = article_store.cleanup_expired()
    log.info("daily_cleanup", deleted=deleted)
    _cleanup_archive()


class ProgramClock:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(
            job_defaults={"misfire_grace_time": 60}
        )

    def start(self) -> None:
        # Restore recent MP3s from cache (crash recovery)
        restored = audio_queue.restore_from_cache(config.CACHE_DIR, max_age_hours=2)
        if restored == 0:
            log.info("cache_restore_empty")

        # Pre-generate fallback audio segments in background
        init_fallback()

        # Main pipeline: every 15 minutes
        self._scheduler.add_job(
            run_content_pipeline,
            trigger=IntervalTrigger(minutes=config.FETCH_INTERVAL_MINUTES),
            id="content_pipeline",
            name="Content Pipeline",
            replace_existing=True,
        )

        # Watchdog: every 30 seconds
        self._scheduler.add_job(
            run_watchdog,
            trigger=IntervalTrigger(seconds=config.WATCHDOG_INTERVAL_SECONDS),
            id="watchdog",
            name="Queue Watchdog",
            replace_existing=True,
        )

        # Station ID: every hour at :00
        self._scheduler.add_job(
            run_station_id,
            trigger=CronTrigger(minute=0),
            id="station_id",
            name="Station ID",
            replace_existing=True,
        )

        # Daily cleanup at midnight KST (15:00 UTC)
        self._scheduler.add_job(
            run_daily_cleanup,
            trigger=CronTrigger(hour=15, minute=0),
            id="daily_cleanup",
            name="Daily Cleanup",
            replace_existing=True,
        )

        self._scheduler.start()
        log.info("program_clock_started")

        # Kick off immediately on startup
        threading.Thread(
            target=run_content_pipeline, daemon=True, name="initial-pipeline"
        ).start()

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("program_clock_stopped")


# Global singleton
program_clock = ProgramClock()
