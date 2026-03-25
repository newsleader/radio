# NewsLeader Continuous Improvement Log

## 2026-03-25

### PR #4 — fix: skip GDELT in emergency mode + raise BUFFER_LOW to 300s
- Skip GDELT (always 0 articles, ~2min waste) when emergency=True
- BUFFER_LOW 180s → 300s: emergency fires earlier, more headroom

### PR #5 — feat: tighten news freshness
- MAX_ARTICLE_AGE_HOURS: 24h → 8h
- MAX_ARTICLES_PER_FEED: 5 → 8
- FETCH_INTERVAL_MINUTES: 15 → 10
- Recency scoring: linear 2h → exponential 90-min half-life

### PR #6 — feat: algorithm improvements
- Event clustering: single-linkage → complete-linkage (prevents chain merging)
- Editorial quota: fixed hourly → 20-min sliding window
- Clustering body text window: 300 → 600 chars

### PR #7 — feat: UI overhaul
- Modern CSS with system fonts and CSS variables
- Pulsing red live indicator
- Buffer bar (queue health visualized)
- SSE /events endpoint (2s push vs 10s polling)
- Real-time stats: listeners, queue, pipeline age
- Archive path traversal fix (symlink-safe)

### PR #8 — fix: misc improvements
- Embedding body window: 300 → 800 chars
- Feed backoff jitter ±25%
- Health /health Cache-Control: no-store on 503

### PR #9 — fix: algorithm tuning + AsyncLimiter event-loop fix
- Complete-linkage clustering threshold: 0.45 → 0.30 (too strict → 107→106 clusters)
- AsyncLimiter: create fresh per event-loop call (was global dict, caused RuntimeWarning)

### PR #10 — fix: fetcher performance + logging
- TCPConnector limit: 15 → 30 (81 feeds need more concurrent slots)
- FETCH_TIMEOUT: 20s → 10s (faster fail on dead feeds)
- Feed error logging: add exc_type field for empty-message exceptions
- Station ID: 4 rotating Korean variants instead of fixed message

### PR #11 — feat: expand TTS preprocessing
- % → 퍼센트, pp → 퍼센트포인트, bps → 베이시스포인트
- °C/°F → 섭씨N도/화씨N도
- miles, lbs, tons, kW unit conversions
- ₩ Korean won currency symbol
- New acronyms: AI, ESG, FTA, G7, G20, EV, LNG, LPG
- Acronyms sorted longest-first to prevent partial matches

### PR #12 — fix: iOS background audio + UI cleanup
- iOS screen sleep: audio continues via mediaSession API (lock screen controls)
- playsinline attribute: prevents iOS fullscreen video takeover
- apple-mobile-web-app-capable meta tags for PWA-like behavior
- visibilitychange: resumes audio when screen unlocks
- Cache restore title: '[캐시 복원]' → 'NewsLeader Radio'
- mediaSession title updates in real-time from SSE

### PR #14 — fix: skip aired articles on cache restore + fix simhash=0
- mark_seen: add aired=True parameter, store in DB
- restore_recent_cache: filter out url_hashes with aired=1
- program_clock: pass aired=True to mark_seen after TTS
- program_clock: fix simhash_value=0 hardcode → compute_simhash()

### PR #15 — fix: mark restored files as aired immediately (hotfix)
- On cache restore, immediately mark restored files as aired=1 in DB
- Insert stub rows for cache files not yet in DB (pre-fix articles)
- This prevents the same 10 articles from repeating on EVERY restart
- Result: after this restart, cache_restore_empty on next boot (confirmed)

### PR #13 — fix: LLM max_tokens + QA tightening
- LLM call: add max_tokens=4096 (prevents empty output on thinking models)
- QA min word count: 80 → 120 (target is 170-210; 80 was too lenient)
- QA: add bracket check — (), [], 【】 banned by prompt, now enforced by QA

### PR #16 — fix: simhash SQLite overflow + auto-strip brackets
- compute_simhash: unsigned 64-bit → signed 64-bit (_to_signed64) to prevent 'Python int too large to convert to SQLite INTEGER' pipeline crash
- script_generator: strip ()[]【】{}「」 in NewsScriptResponse validator and plain-text fallback path (eliminates BRACKETS_FOUND QA retries at source)

### PR #17 — fix: widen QA closing phrase regex {1,30} → {1,60}
- Long Korean topic names (>30 chars) were triggering spurious CLOSING_MISSING QA failures despite correct closing phrases
- scripts_qa_failed now 0 (confirmed) — pipeline runs cleanly

### PR #18 — feat: Korean LLM topic as now-playing display title
- generate_script() now returns (script, topic) tuple
- program_clock.py uses Korean topic (e.g. '독일 혹등고래 구조 및 핵 폐기물 운송') as display title
- Falls back to English article title if topic is empty
- now_playing in status/SSE shows Korean instead of English article titles

### PR #19 — fix: GDELT early-stop on 429 + extend interval 900s→1800s
- On 429 rate limit, abort remaining batch queries immediately (was sleeping 6s each → 24+ sec wasted)
- _MIN_INTERVAL: 900s → 1800s (30min) to reduce 429 frequency

### PR #20 — fix: pass url to trafilatura.extract (suppress discarding data warning)
- trafilatura logged 'discarding data: None' warning when called without a URL parameter
- Added url= to both trafilatura.extract() call sites in fetcher.py

### PR #21 — fix: cap feed backoff 240min→60min + reset 114 stuck feeds
- 4-hour max backoff meant major feeds (Yonhap, Hani, MK, Korea Herald) stuck for hours after transient outage
- 60min cap: faster recovery while still protecting against dead feeds
- Reset 114 feeds from deep backoff so they retry on next pipeline run

### PR #22 — fix: TCPConnector limit 30→80, FETCH_TIMEOUT 10s→15s
- 169 feeds × 30 connection slots: last feeds waited 9+ sec in pool queue → exceeded 10s total timeout
- 80 slots = at most 2 rounds → queue wait ≤3s → articles_fetched: 94 (was 0 due to all feeds timing out)
