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
