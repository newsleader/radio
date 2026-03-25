"""
GDELT (Global Database of Events, Language, and Tone) integration.

GDELT provides near-real-time global news event data including:
  - Top trending news articles every 15 minutes
  - Tone/sentiment scores
  - Geographic and thematic metadata

We use the GDELT 2.0 GKG (Global Knowledge Graph) API to fetch
trending Korean-relevant news articles not covered by RSS feeds.

API endpoint: https://api.gdeltproject.org/api/v2/doc/doc
  - mode=ArtList: returns article list
  - query: search terms
  - format=json
  - timespan=15min: last 15 minutes only
  - maxrecords=10

Free, no auth required. Rate limit: ~1 req/5s per IP.
"""
import asyncio
import time

import aiohttp
import structlog

from pipeline.fetcher import Article

log = structlog.get_logger(__name__)

_GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_LAST_FETCH: float = 0.0
_MIN_INTERVAL = 900.0   # 15 minutes between GDELT fetches (rate limit 회복)

# Queries to search on GDELT — diverse global coverage for Korean listeners
# GDELT 문법: OR 표현식은 반드시 괄호로 감싸야 함
_GDELT_QUERIES = [
    # 한국 경제
    '(Korea economy) OR ("Korean won") OR KOSPI OR ("Bank of Korea")',
    # 글로벌 매크로
    '("Federal Reserve") OR ("interest rate") OR ("oil price") OR semiconductor',
    # 한반도 지정학
    '("North Korea") OR ("South Korea") OR ("Korean peninsula") OR DPRK',
    # AI / 기술 최신
    '("artificial intelligence") OR ChatGPT OR OpenAI OR Anthropic OR Claude OR Gemini',
    # 미중 무역
    '("US China") OR ("trade war") OR tariff OR Taiwan OR ("supply chain")',
    # 중동 / 지정학
    'Iran OR ("Middle East") OR Gaza OR Israel OR ("oil embargo")',
    # 기후 / 환경
    '("climate change") OR ("global warming") OR ("renewable energy") OR ("carbon emissions")',
    # 과학 / 우주
    'NASA OR SpaceX OR ("space exploration") OR ("scientific discovery") OR ("gene editing")',
    # 스포츠
    'Olympics OR FIFA OR baseball OR ("World Cup") OR ("Champions League")',
    # 유럽 경제
    'eurozone OR ECB OR ("European Union") OR Germany OR France',
    # 아시아 / 동남아
    'ASEAN OR ("Southeast Asia") OR Japan OR China OR India OR ("Asia Pacific")',
    # 금융시장
    '("stock market") OR cryptocurrency OR bitcoin OR ("Wall Street") OR ("hedge fund")',
    # 건강 / 의학
    'WHO OR pandemic OR vaccine OR ("drug approval") OR ("clinical trial")',
    # 사회 / 문화
    '("Korean culture") OR ("K-pop") OR ("Korean drama") OR hallyu OR BTS',
    # 에너지 / 자원
    '("natural gas") OR OPEC OR ("nuclear energy") OR battery OR EV',
    # 사이버보안
    'cyberattack OR ransomware OR ("data breach") OR hacking OR ("zero-day") OR malware',
    # 크립토 / 코인
    'bitcoin OR ethereum OR cryptocurrency OR ("crypto market") OR ("digital asset") OR DeFi',
    # 주식 / 기업 실적
    '("earnings report") OR ("quarterly results") OR ("stock surge") OR ("market rally") OR IPO',
    # 거시경제 흐름
    '("GDP growth") OR inflation OR recession OR ("monetary policy") OR stagflation',
]

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def _fetch_gdelt_query(
    session: aiohttp.ClientSession,
    query: str,
    timespan: str = "1h",
    max_records: int = 10,
) -> list[Article]:
    """Fetch articles from GDELT for a single query."""
    params = {
        "query": query,
        "mode": "ArtList",
        "timespan": timespan,
        "maxrecords": str(max_records),
        "format": "json",
        "sort": "ToneDesc",   # highest tone (most positive/significant) first
    }
    try:
        async with session.get(
            _GDELT_BASE,
            params=params,
            timeout=_FETCH_TIMEOUT,
        ) as resp:
            if resp.status == 429:
                log.warning("gdelt_rate_limited_429", query=query[:60])
                return []
            if resp.status != 200:
                log.debug("gdelt_non_200", status=resp.status, query=query[:60])
                return []
            text = await resp.text()
            # rate limit 또는 오류 텍스트 감지
            if text.startswith("Please limit") or text.startswith("Queries") or text.startswith("Timespan"):
                log.warning("gdelt_rate_limited", msg=text[:80])
                return []
            import json as _json
            data = _json.loads(text)

    except Exception as exc:
        log.debug("gdelt_fetch_error", error=str(exc)[:100])
        return []

    articles: list[Article] = []
    for item in (data.get("articles") or []):
        url = item.get("url", "")
        title = item.get("title", "").strip()
        source = item.get("domain", "GDELT")
        if not url or not title or len(title) < 10:
            continue

        articles.append(Article(
            url=url,
            title=title,
            source=f"GDELT/{source}",
            body=title,   # no full body from GDELT API — title only
            published=item.get("seendate", None),
        ))

    return articles


_QUERY_CURSOR = 0  # 순환 커서 — 매 실행마다 다른 쿼리 그룹 사용

async def fetch_gdelt_articles() -> list[Article]:
    """
    Fetch trending global news from GDELT relevant to Korean listeners.
    Rate-limited to once every 15 minutes.
    5개 쿼리씩 순차 실행 (GDELT rate limit: 1 req/5s 준수).
    19개 쿼리를 순환하여 매 실행마다 다른 주제 커버.
    """
    global _LAST_FETCH, _QUERY_CURSOR
    now = time.monotonic()
    if now - _LAST_FETCH < _MIN_INTERVAL:
        log.debug("gdelt_skipped_rate_limit")
        return []

    _LAST_FETCH = now

    # 5개씩 순환 선택
    BATCH = 5
    start = _QUERY_CURSOR % len(_GDELT_QUERIES)
    selected = (_GDELT_QUERIES + _GDELT_QUERIES)[start:start + BATCH]
    _QUERY_CURSOR = (start + BATCH) % len(_GDELT_QUERIES)

    log.info("gdelt_fetch_start", queries=BATCH, cursor=start)

    articles: list[Article] = []
    seen_urls: set[str] = set()

    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        for i, query in enumerate(selected):
            if i > 0:
                await asyncio.sleep(6)  # GDELT rate limit: 1 req/5s 준수
            result = await _fetch_gdelt_query(session, query)
            for a in result:
                if a.url not in seen_urls:
                    seen_urls.add(a.url)
                    articles.append(a)

    log.info("gdelt_fetch_complete", articles=len(articles))
    return articles
