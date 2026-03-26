# NewsLeader Continuous Improvement Log

## 2026-03-26

### PR #51 — fix: expand non-news title filter (Hive Life, weekly roundups, MK screeners)
- `Hive Life:` prefix (Macro Hive lifestyle articles) → fluffy non-finance scripts
- `Week in Review / Weekly Roundup / Weekly Recap` → compilation summaries redundant when individual stories already aired
- `[MK 상한가/하한가/특징주/급등/급락]` → MK automated stock screener alerts (like 골든크로스, these cause LLM hallucination)
- `상한가 종목 / 하한가 종목` → Korean stock upper/lower limit screener lists (thin data → LLM hallucinates to fill word count)

### PR #50 — fix: prefer Korean topic from closing phrase when JSON topic is English
- `gemma3:12b` sometimes returns English title as JSON topic for English-sourced articles
- Fix: if meta_topic has no Korean chars, extract from `이상으로 [topic] 소식이었습니다.` closing phrase
- Korean-titled articles unaffected; English-source articles now show Korean in ICY/now_playing

### PR #49 — fix: lower QA word floor to 100 for breaking news
- 속보 articles with thin source material: LLM generates 138 words → QA fails → retry → 112 words (worse) → skipped
- Breaking news uses min_words=100 via `is_breaking=True` in generate_script; regular articles keep 150-word floor
- No retry for thin 속보 — first attempt at 100-149 words airs without a harmful retry that makes things worse

### PR #48 — fix: per-cluster dedup — only one article per news event per pipeline run
- Different Korean feeds carry the same story with slightly different titles → both passed title-hash/simhash/in-run dedup → same story aired twice in same run
- cluster_id_map: {url → canonical_url} for multi-source clusters; seen_cluster_ids tracks aired clusters per run
- After first article from a cluster airs, rest are `cluster_dup_skipped`; single-source clusters unaffected

### PR #47 — fix: filter 골든크로스/데드크로스 stock screener titles
- These automated screener alerts reached LLM and caused hallucinated scripts (LLM invented discount promotions)
- Added `골든크로스|데드크로스` to `_NON_NEWS_TITLE_RE` — filtered before body HTTP fetch

### PR #46 — fix: skip article when WORD_COUNT fails after retry
- PR #45 loophole: 130-word script fails QA → retry → still 130 words → `>= 50 words` fallback used it anyway
- Fix: `WORD_COUNT` failures skip the `>= 50 word` fallback; minor failures (BRACKETS, CLOSING_MISSING) still use it
- Short scripts no longer air via the back door

### PR #45 — fix: raise QA min word count 120→150 + remove Netflix Tech Blog feed
- QA min word count: 120 → 150 — scripts at 130-149 words now fail QA and get retry with WORD_COUNT feedback
- With gemma3:12b, last run produced scripts at 130, 143, 155, 161 words — the 120 threshold was never triggering retries
- Netflix Tech Blog removed: avg_latency=27113ms always exceeds 20s FETCH_TIMEOUT; engineering blog not news; was in permanent fail→backoff→retry→timeout cycle

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

### PR #34 — fix: FETCH_TIMEOUT 15s→20s + reset 48 stuck feeds
- 24 feeds have avg_latency 15-27s (netflixtech=27s, straitstimes/koreaherald/scmp=20s, yonhap/hani=17-18s, etc.)
- These feeds timeout at 15s → consecutive_failures++ → 60-min backoff → retry → timeout again
- After overnight: 48 feeds at 8-17 consecutive failures, articles_fetched dropped 120→54
- FETCH_TIMEOUT 15s→20s covers all but the most extreme (netflixtechblog at 27s avg)
- Also manually reset 48 feeds from ≥8 failures → 3 failures + next_check_at=now for immediate retry

### PR #33 — fix: TCPConnector limit 80→len(RSS_FEEDS) (130)
- With limit=80 and 130 feeds, last 50 feeds waited for a slot
- aiohttp ClientTimeout(total=15) includes pool-wait time → feeds with 3s pool wait + 13s HTTP = timeout
- Setting limit=len(RSS_FEEDS) = 0 pool wait, every feed gets full timeout budget for HTTP
- Resolves root cause of slow feeds failing despite being within timeout

### PR #32 — fix: suppress trafilatura/htmldate/apscheduler verbose logging
- trafilatura + htmldate log at ERROR level for normal extraction failures ("discarding data", "empty HTML tree", "parsed tree length") — not actionable, silenced with CRITICAL
- apscheduler logs "Job executed successfully" at INFO every 30s (watchdog = 2,880 lines/day) — silenced at WARNING (keeps misfires/errors visible)
- Applied in both wsgi.py (production) and main.py (local dev)

### PR #27 — fix: healthcheck start_period 60s→180s (prevent autoheal restart loop)
- Race condition: health check fails at ~100s (60s start + 3×20s retries), first audio arrives at 90-130s
- autoheal restarted container 10 times in 20 min at 02:46-03:05 UTC when cache was empty
- start_period=180s gives 90s headroom over worst-case startup; AUTOHEAL_START_PERIOD=180 for consistency

### PR #26 — fix: skip GDELT when RSS fetches ≥30 articles
- GDELT consistently returns 0 articles while taking ~100s per scheduled run
- RSS reliably fetches 113+ articles → GDELT provides zero additional value
- Skip GDELT when rss_articles >= 30; still activates if RSS degrades to <30 (fallback preserved)
- Combined with PR #25: GDELT now disabled under all normal operating conditions

### PR #25 — fix: skip GDELT when buffer < BUFFER_LOW (300s)
- GDELT 5 queries × ~20s timeout = ~100s total, returns 0 articles, but ran on every restart
- After restart _LAST_FETCH resets to 0 → first pipeline always waited 100s before producing audio
- watchdog_critical fired every 30s during GDELT phase (16s silence gaps)
- Fix: skip GDELT when buffered_seconds < BUFFER_LOW — fill queue with RSS articles first
- GDELT still runs normally when buffer ≥ 300s (extends PR #4 emergency skip)

### PR #24 — fix: BUFFER_FULL 600s→900s (prevent buffer dip near critical)
- With 600s FULL threshold and 10min pipeline interval: queue drains from 600s to ~0s between runs
- Observed: buffer dipped to 154s (10:54) while pipeline was already running and couldn't add content fast enough
- 900s FULL: pipeline builds 5 more minutes of buffer headroom → after 10min drain, ~300s remains (above BUFFER_LOW)
- Eliminates the 154s near-critical event while keeping content fresh (900s = 15min max age)

### PR #31 — fix: add TTS cache cleanup (delete files >4h old) on every pipeline run
- cache/ directory grows without bound: no cleanup existed → 385MB / 239 files after one dev session
- New _cleanup_cache(): deletes cache/*.mp3 and cache/*.title older than 4h (2× the 2h restore window)
- Skips cache/fallback/ subdirectory (permanent fallback audio)
- Called on every pipeline run (cheap mtime scan) + in run_daily_cleanup()
- Max disk usage after fix: ~150-200MB (4h × typical runs × 1.6MB/file)

### PR #30 — fix: fallback count 4→5 to eliminate 2s silence gap between critical events
- 27.8s (count=4) < 30s watchdog interval → 2.2s silence every 30s during cold startup
- 35.2s (count=5, round-robin wraps 0→1→2→3→0) > 30s → no silence between critical cycles
- Buffer at next critical check = 35.2 - 30 = 5.2s (small but non-zero) → no audible gap

### PR #29 — fix: fallback files to cache/fallback/ subdir + title sidecar on restore
- PR #28 bug: fallback_N.mp3 in cache root → picked up by restore_recent_cache glob → 7-8s placeholder audio played as "NewsLeader Radio" on restart
- Fix: cache/fallback/N.mp3 subdirectory not matched by cache/*.mp3 glob
- Also: program_clock writes cache/{cache_key}.title alongside each MP3; restore_from_cache reads title sidecar → restored articles show proper Korean topic name in ICY metadata

### PR #28 — fix: persist fallback audio to disk + critical count 2→4
- Fallback pool generation took ~40s (4 TTS calls) — watchdog_critical at T=30s and T=60s fired with empty pool, enqueue_fallback() silently returned 0 (no coverage)
- Now saves cache/fallback_N.mp3 after first TTS generation; subsequent restarts load from disk in <1ms
- count=4 at critical: enqueues all 4 scripts (~28s total) vs 2 scripts (~14s)
- Result: on restarts with empty queue, fallback audio is immediately available and provides ~28s of coverage per critical event

### PR #39 — fix: extract Korean topic from closing phrase when JSON topic is empty
- When JSON parsing fails, meta_topic=None → display_title falls back to English article title in ICY metadata
- Fix: regex extracts topic from '이상으로 [topic] 소식이었습니다.' closing phrase
- Topic capped at 40 chars for ICY compatibility

### PR #38 — feat: track articles_filtered_title/body in /status counters
- New counters: articles_filtered_title (non-news title regex), articles_filtered_body (thin body < 300 chars)
- Visible in /status JSON and /metrics Prometheus format

### PR #37 — fix: QA-feedback retry prompt + filter Japanese earthquake alerts
- LLM retry on QA failure now appends specific correction text (was same prompt → same failure)
- _build_retry_feedback(): WORD_COUNT → current count + add more context, CLOSING_MISSING → exact phrase, LIST_FORMAT → identifies pattern, OPENING_WRONG → reminder
- 【地震情報】 added to _NON_NEWS_TITLE_RE: NHK earthquake alerts (M3, location+magnitude only) always fail WORD_COUNT (95-106 words), not relevant to Korean audience

### PR #36 — fix: tighten breaking news keywords to reduce false positives
- 부상 → 부상자|부상을 (rise/emergence 부상 was triggering for tech "클라우드 네이티브 신원 관리 부상")
- 선언 removed (too broad: product launches use this), 비상 → 비상사태 (state of emergency specifically)

### PR #35 — fix: pre-filter non-news titles + raise body minimum 100→300 chars
- Articles like [투자운세] horoscopes, software changelogs (datasette-llm 0.1a1), event listings (Demo Day Dates) reached LLM and caused WORD_COUNT/CLOSING_MISSING QA failures
- _NON_NEWS_TITLE_RE: regex check before body HTTP fetch (saves round-trip) — blocks 운세/점성/별자리, package vX.Yaz release titles, changelog keyword, demo day dates
- MIN_BODY_LENGTH: 100 → 300 chars (120-word scripts need ~400 chars of source; 100 was too lenient)

### PR #41 — fix: skip article on LLM refusal instead of minimal fallback
- generate_minimal_fallback() inserts raw article title (often English) into 2-sentence template → 20-word English-title script bypasses QA and airs
- Example: "e's new Dynamic Workers ditch containers to run AI agent code 100x faster. 이상으로 VentureBeat 소식이었습니다." (words=20)
- Fix: on detect_refusal=True, break without setting script → generate_script returns None → article silently skipped

### PR #44 — fix: stronger QA retry feedback for LIST_FORMAT and WORD_COUNT
- LIST_FORMAT: old message "각 항목을 독립 문장으로 서술하세요" too vague → BFC article used '셋째' on both attempts
- New: explicitly names detected words, bans 첫째/둘째/셋째/넷째/①②③④/△, provides concrete example conversion
- WORD_COUNT: now shows exact deficit ("58어절 부족"), lists 4 content types to add, requires "8문장 이상"

### PR #43 — fix: in-run title dedup to prevent same 속보 airing twice
- Race condition: multiple feeds fetch same article simultaneously → both pass fetcher's title-hash check (DB not updated yet) → same story airs twice in one pipeline run
- Observed: 25조 추경 예산안 aired at 00:11 and 00:13 (2 min apart, same pipeline run)
- Fix: seen_titles_this_run set in run_content_pipeline() — skip articles with already-queued title
- Placed AFTER breaking_detector.check_and_register() so multi-feed coverage still boosts importance

### PR #42 — feat: add cybersecurity as dedicated editorial category
- Security articles (Krebs, Bleeping Computer, The Hacker News, CISA, Unit 42, Malwarebytes, Schneier, Recorded Future, 보안뉴스) all bucketed into tech → consuming all 5 tech slots per window
- New cybersecurity category: 23 keywords, 9 source tiers, _MAX_PER_WINDOW=3
- Source fallback: security sources detected before tech fallback; "hacker" removed from tech (was matching "The Hacker News")

### PR #40 — fix: per-source pipeline cap (max 2 articles per source per run)
- 6 crypto sources (CoinDesk, CoinTelegraph, Decrypt, Bitcoin Magazine, 블록미디어, 토큰포스트) could each contribute 8 articles → 48 crypto candidates per run
- MMR diversifies by content similarity, not source identity → two CoinDesk articles on different subtopics both passed
- Add _MAX_PER_SOURCE=2 in pipeline loop; breaking news bypasses; count only increments after TTS success (editorial skips don't consume quota)
- Effect: any single outlet limited to 2 articles per pipeline run; crypto cap ≤ 2 per source = max ~12 combined (editorial window further limits to 6 finance)

### PR #23 — fix: remove 39 dead feeds (169→130)
- 39 feeds had last_success_at=NULL (never worked from Docker environment)
- Removed: Reddit r/worldnews|technology|science (block RSS without auth), FeedBurner URLs (securityweek, zerohedge — deprecated), SCMP Technology+Asia, Korea Herald World, KBS World, Google AI Blog, Google Project Zero, HBR, Hacker News (hnrss.org), IEEE Spectrum, Tom's Hardware, Dark Reading, SecurityWeek, Middle East Eye, 데일리시큐, AI News, Radio Free Asia, 코인데스크 코리아, The Block, The Batch (deeplearning.ai), 이데일리 (×2), 머니투데이, 서울경제, SBS뉴스, 조선비즈, 연합뉴스 사회, 기획재정부, 금융위원회, 공정거래위원회, WHO News, Carbon Brief, NBER, St. Louis Fed, Investopedia, Anthropic News
- Updated exclusion comment in feeds.py header
