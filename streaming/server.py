"""
Flask HTTP streaming server.

Endpoints:
  GET /stream      — ICY-compatible infinite MP3 stream (with optional metadata)
  GET /listen.m3u  — M3U playlist
  GET /            — HTML5 player with auto-reconnect
  GET /health      — detailed health check
  GET /status      — JSON status
  GET /metrics     — Prometheus text metrics
  GET /events      — SSE stream for live now-playing updates
"""
import json
import time
from flask import Flask, Response, request, send_file, stream_with_context
from pathlib import Path

import structlog

from config import config
from streaming.broadcaster import broadcaster, ICY_METAINT

log = structlog.get_logger(__name__)

app = Flask(__name__)

# ── Shared CSS ─────────────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #0a0a0a;
  --surface: #111;
  --border: #222;
  --border-active: #444;
  --text: #e8e8e8;
  --muted: #555;
  --accent: #fff;
  --live: #e84040;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic', sans-serif;
  --mono: 'SF Mono', 'Consolas', 'Malgun Gothic', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 15px; }
body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.55;
}
a { color: var(--text); text-decoration: none; }
a:hover { color: var(--accent); }

.layout {
  max-width: 720px;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 4rem;
}

/* Header */
.hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 2.5rem;
}
.hdr-brand {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
}
.hdr-nav {
  display: flex;
  gap: 1.5rem;
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.hdr-nav a { color: var(--muted); transition: color .15s; }
.hdr-nav a:hover, .hdr-nav a.on { color: var(--text); }

/* Live badge */
.badge-live {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-family: var(--mono);
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  color: var(--live);
  text-transform: uppercase;
}
.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--live);
  flex-shrink: 0;
}
.dot.pulse { animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: .4; transform: scale(.7); }
}

/* Player card */
.player-card {
  border: 1px solid var(--border);
  padding: 1.4rem 1.5rem;
  margin-bottom: 1px;
}
.player-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.1rem;
}
.now-label {
  font-size: 0.65rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.4rem;
}
.now-title {
  font-size: 0.92rem;
  font-weight: 500;
  min-height: 1.4rem;
  line-height: 1.4;
}
.player-audio {
  width: 100%;
  filter: invert(1) hue-rotate(180deg);
  opacity: .85;
  margin-bottom: 0.75rem;
}
.player-status {
  font-size: 0.72rem;
  color: var(--muted);
  font-family: var(--mono);
}

/* Buffer bar */
.buf-row {
  border: 1px solid var(--border);
  margin-bottom: 1px;
  padding: 0.8rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}
.buf-label {
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  white-space: nowrap;
  width: 4.5rem;
  flex-shrink: 0;
}
.buf-track {
  flex: 1;
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.buf-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width .6s ease;
  width: 0%;
}
.buf-val {
  font-size: 0.7rem;
  font-family: var(--mono);
  color: var(--muted);
  width: 3.5rem;
  text-align: right;
  flex-shrink: 0;
}

/* Stats row */
.stats-row {
  border: 1px solid var(--border);
  margin-bottom: 2rem;
  padding: 0.7rem 1.5rem;
  display: flex;
  gap: 2rem;
  font-size: 0.72rem;
  font-family: var(--mono);
  color: var(--muted);
}
.stat span { color: var(--text); margin-left: 0.4em; }

/* Section label */
.sec-label {
  font-size: 0.65rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.6rem;
}

/* Date / track rows */
.row-link {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border: 1px solid var(--border);
  margin-bottom: -1px;
  padding: 0.75rem 1.2rem;
  font-size: 0.84rem;
  color: var(--text);
  transition: border-color .12s;
}
.row-link:hover { border-color: var(--border-active); z-index: 1; position: relative; }
.row-link .cnt { font-size: 0.7rem; color: var(--muted); font-family: var(--mono); }

/* Archive date page */
.sticky-player {
  position: sticky;
  top: 0;
  background: var(--bg);
  border: 1px solid var(--border);
  border-bottom-color: var(--border-active);
  padding: 1rem 1.2rem;
  margin-bottom: 1.5rem;
  z-index: 10;
}
.sticky-now {
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 0.55rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sticky-now.on { color: var(--text); }
.sticky-audio { width: 100%; filter: invert(1) hue-rotate(180deg); }

.track-row {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  border: 1px solid var(--border);
  margin-bottom: -1px;
  padding: 0.65rem 1.2rem;
  cursor: pointer;
  transition: border-color .12s;
}
.track-row:hover, .track-row.on { border-color: var(--border-active); z-index: 1; position: relative; }
.track-time { font-size: 0.68rem; color: var(--muted); font-family: var(--mono); white-space: nowrap; flex-shrink: 0; }
.track-title { font-size: 0.84rem; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }

.empty { font-size: 0.82rem; color: var(--muted); padding: 1rem 0; }
"""

# ── Live player ────────────────────────────────────────────────────────────────

_PLAYER_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newsleader — Live</title>
  <style>STYLE_PLACEHOLDER</style>
</head>
<body>
<div class="layout">
  <header class="hdr">
    <span class="hdr-brand">Newsleader</span>
    <nav class="hdr-nav">
      <a href="/" class="on">Live</a>
      <a href="/archive">Archive</a>
    </nav>
  </header>

  <div class="player-card">
    <div class="player-top">
      <div>
        <p class="now-label">Now Playing</p>
        <div class="now-title" id="np">—</div>
      </div>
      <span class="badge-live" id="badge">
        <span class="dot" id="dot"></span>
        <span id="badge-txt">Connecting</span>
      </span>
    </div>
    <audio class="player-audio" id="audio" controls autoplay>
      <source src="/stream" type="audio/mpeg">
    </audio>
    <p class="player-status" id="pstatus">128 kbps · MP3 · Mono</p>
  </div>

  <div class="buf-row">
    <span class="buf-label">Buffer</span>
    <div class="buf-track"><div class="buf-fill" id="bufbar"></div></div>
    <span class="buf-val" id="bufval">—</span>
  </div>

  <div class="stats-row" id="statsrow">
    <span>Listeners<span id="s-listeners">—</span></span>
    <span>Queue<span id="s-queue">—</span></span>
    <span>Pipeline<span id="s-pipe">—</span></span>
  </div>

  <p class="sec-label">Stream</p>
  <a class="row-link" href="/listen.m3u">
    <span>listen.m3u</span>
    <span class="cnt">Open in VLC / media player</span>
  </a>
</div>

<script>
(function(){
  var audio   = document.getElementById('audio');
  var np      = document.getElementById('np');
  var dot     = document.getElementById('dot');
  var badgeTxt = document.getElementById('badge-txt');
  var pstatus = document.getElementById('pstatus');
  var bufbar  = document.getElementById('bufbar');
  var bufval  = document.getElementById('bufval');
  var RECONNECT_BASE = 3000, RECONNECT_MAX = 30000;
  var delay = RECONNECT_BASE, timer = null;
  var BUFFER_MAX = 600;  // seconds, full watermark

  function setLive(on) {
    dot.className = on ? 'dot pulse' : 'dot';
    badgeTxt.textContent = on ? 'Live' : 'Buffering';
    if (on) delay = RECONNECT_BASE;
  }

  function reconnect() {
    clearTimeout(timer);
    setLive(false);
    pstatus.textContent = 'Reconnecting...';
    timer = setTimeout(function() {
      audio.src = '/stream?t=' + Date.now();
      audio.load(); audio.play().catch(function(){});
      delay = Math.min(delay * 2, RECONNECT_MAX);
    }, delay);
  }

  audio.addEventListener('playing', function() {
    setLive(true);
    pstatus.textContent = '128 kbps · MP3 · Mono';
  });
  audio.addEventListener('error',   function() { pstatus.textContent = 'Error'; reconnect(); });
  audio.addEventListener('stalled', function() { setLive(false); pstatus.textContent = 'Buffering...'; clearTimeout(timer); timer = setTimeout(reconnect, 8000); });
  audio.addEventListener('waiting', function() { setLive(false); pstatus.textContent = 'Buffering...'; });

  // SSE for now-playing updates
  function connectSSE() {
    var es = new EventSource('/events');
    es.onmessage = function(e) {
      try {
        var d = JSON.parse(e.data);
        if (d.now_playing) np.textContent = d.now_playing;
        if (typeof d.buffered_seconds !== 'undefined') {
          var pct = Math.min(d.buffered_seconds / BUFFER_MAX * 100, 100);
          bufbar.style.width = pct + '%';
          bufval.textContent = d.buffered_seconds > 0 ? Math.round(d.buffered_seconds) + 's' : '—';
        }
        if (typeof d.listeners !== 'undefined') {
          document.getElementById('s-listeners').textContent = ' ' + d.listeners;
        }
        if (typeof d.buffered_seconds !== 'undefined') {
          document.getElementById('s-queue').textContent = ' ' + Math.round(d.buffered_seconds) + 's';
        }
        if (d.pipeline) {
          var ago = d.pipeline.last_run_ago_s;
          document.getElementById('s-pipe').textContent = ago != null ? ' ' + Math.round(ago) + 's ago' : ' —';
        }
      } catch(ex){}
    };
    es.onerror = function() {
      es.close();
      setTimeout(connectSSE, 5000);
    };
  }
  connectSSE();
})();
</script>
</body>
</html>"""

_PLAYER_HTML = _PLAYER_HTML.replace("STYLE_PLACEHOLDER", _CSS)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return _PLAYER_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/events")
def sse_events():
    """Server-Sent Events stream for real-time now-playing / queue status."""
    @stream_with_context
    def generate():
        while True:
            try:
                from pipeline.queue_manager import audio_queue
                data = {
                    "now_playing": audio_queue.current_title,
                    "buffered_seconds": round(audio_queue.buffered_seconds, 1),
                    "listeners": broadcaster.listener_count,
                    "pipeline": {
                        "last_run_ago_s": None,
                    },
                }
                try:
                    from monitoring.health import _last_pipeline_run, _last_pipeline_success
                    import time as _time
                    if _last_pipeline_run:
                        data["pipeline"]["last_run_ago_s"] = round(_time.time() - _last_pipeline_run)
                except Exception:
                    pass
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except Exception:
                yield "data: {}\n\n"
            time.sleep(2)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/stream")
def audio_stream():
    """ICY-compatible infinite MP3 stream."""
    client_ip = request.remote_addr
    log.info("stream_request", ip=client_ip)

    want_metadata = request.headers.get("Icy-Metadata", "0").strip() == "1"

    cid, q = broadcaster.add_listener()

    def generate():
        try:
            yield from broadcaster.stream_client(cid, q, want_metadata=want_metadata)
        except Exception as exc:
            log.warning("stream_error", client_id=cid, error=str(exc))
            broadcaster.remove_listener(cid)

    headers = {
        "Content-Type":           "audio/mpeg",
        "Cache-Control":          "no-cache, no-store",
        "Pragma":                 "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Accel-Buffering":      "no",
        "icy-name":    "NewsLeader Radio",
        "icy-genre":   "News Economy Technology",
        "icy-url":     f"http://localhost:{config.PORT}/",
        "icy-pub":     "1",
        "icy-br":      str(config.MP3_BITRATE),
        "icy-metaint": str(ICY_METAINT) if want_metadata else "0",
    }

    return Response(generate(), headers=headers, status=200)


@app.route("/listen.m3u")
def playlist():
    """M3U playlist for VLC / media players."""
    host = request.host or f"localhost:{config.PORT}"
    m3u = f"#EXTM3U\n#EXTINF:-1,NewsLeader Radio\nhttp://{host}/stream\n"
    return Response(m3u, mimetype="audio/x-mpegurl",
                    headers={"Content-Disposition": "attachment; filename=listen.m3u"})


_ARCHIVE_ROOT = Path("archive")


@app.route("/archive")
def archive_index():
    """Archive index — date list."""
    if not _ARCHIVE_ROOT.exists():
        dates = []
    else:
        dates = sorted(
            [d.name for d in _ARCHIVE_ROOT.iterdir() if d.is_dir()],
            reverse=True
        )

    if "application/json" in request.headers.get("Accept", ""):
        return {"dates": dates}, 200

    date_counts = {d: len(list((_ARCHIVE_ROOT / d).glob("*.mp3"))) for d in dates}

    rows = "".join(
        f'<a href="/archive/{d}" class="row-link">'
        f'<span>{d}</span><span class="cnt">{date_counts[d]} broadcasts</span>'
        f'</a>'
        for d in dates
    ) or '<p class="empty">저장된 방송이 없습니다.</p>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newsleader — Archive</title>
  <style>{_CSS}</style>
</head>
<body>
<div class="layout">
  <header class="hdr">
    <span class="hdr-brand">Newsleader</span>
    <nav class="hdr-nav">
      <a href="/">Live</a>
      <a href="/archive" class="on">Archive</a>
    </nav>
  </header>
  <p class="sec-label">Broadcasts by Date</p>
  {rows}
</div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/archive/<date>")
def archive_date(date: str):
    """Archive day view with inline player."""
    # Path safety: resolve and confirm it's inside archive root
    try:
        date_dir = (_ARCHIVE_ROOT / date).resolve()
        archive_abs = _ARCHIVE_ROOT.resolve()
        date_dir.relative_to(archive_abs)  # raises ValueError if outside
    except (ValueError, OSError):
        return "invalid", 400

    if not date_dir.exists():
        return "not found", 404

    files = sorted([f.name for f in date_dir.glob("*.mp3")])

    if "application/json" in request.headers.get("Accept", ""):
        return {"date": date, "files": files, "count": len(files)}, 200

    def parse_fn(fn):
        parts = fn.split("_", 1)
        t = parts[0].replace("-", ":") if parts else ""
        title = parts[1].replace("_", " ").replace(".mp3", "") if len(parts) > 1 else fn
        return t, title

    track_rows = "".join(
        f'<div class="track-row" onclick="play(\'/archive/{date}/{fn}\')">'
        f'<span class="track-time">{parse_fn(fn)[0]}</span>'
        f'<span class="track-title">{parse_fn(fn)[1]}</span>'
        f'</div>'
        for fn in files
    ) or '<p class="empty">파일이 없습니다.</p>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newsleader — {date}</title>
  <style>{_CSS}</style>
</head>
<body>
<div class="layout">
  <header class="hdr">
    <span class="hdr-brand">Newsleader</span>
    <nav class="hdr-nav">
      <a href="/">Live</a>
      <a href="/archive" class="on">Archive</a>
    </nav>
  </header>

  <div class="sticky-player">
    <div class="sticky-now" id="sn">—</div>
    <audio class="sticky-audio" id="player" controls></audio>
  </div>

  <p class="sec-label">{date} &mdash; {len(files)} broadcasts</p>
  <div id="list">{track_rows}</div>
</div>

<script>
var player = document.getElementById('player');
var sn     = document.getElementById('sn');
var active = null;

function play(src) {{
  document.querySelectorAll('.track-row').forEach(function(t) {{ t.classList.remove('on'); }});
  var all = Array.from(document.querySelectorAll('.track-row'));
  var track = all.find(function(t) {{ return (t.getAttribute('onclick')||'').includes(src.split('/').pop()); }});
  if (track) {{ track.classList.add('on'); active = track; }}
  var title = track ? track.querySelector('.track-title').textContent : src;
  var time  = track ? track.querySelector('.track-time').textContent  : '';
  sn.textContent = (time ? time + '  ' : '') + title;
  sn.classList.add('on');
  player.src = src; player.play();
}}

player.addEventListener('ended', function() {{
  if (!active) return;
  var next = active.nextElementSibling;
  if (next && next.classList.contains('track-row')) {{
    var m = (next.getAttribute('onclick')||'').match(/'([^']+)'/);
    if (m) play(m[1]);
  }}
}});
</script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/archive/<date>/<filename>")
def archive_file(date: str, filename: str):
    """Serve individual broadcast MP3."""
    try:
        file_path = (_ARCHIVE_ROOT / date / filename).resolve()
        archive_abs = _ARCHIVE_ROOT.resolve()
        file_path.relative_to(archive_abs)
    except (ValueError, OSError):
        return "invalid", 400
    if not file_path.exists() or file_path.suffix != ".mp3":
        return "not found", 404
    return send_file(file_path, mimetype="audio/mpeg",
                     as_attachment=False, download_name=filename)


def create_app() -> Flask:
    from monitoring.health import register_routes
    register_routes(app)
    return app
