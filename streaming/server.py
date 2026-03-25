"""
Flask HTTP streaming server.

Endpoints:
  GET /stream      — ICY-compatible infinite MP3 stream (with optional metadata)
  GET /listen.m3u  — M3U playlist
  GET /            — HTML5 player with auto-reconnect
  GET /health      — detailed health check
  GET /status      — JSON status
  GET /metrics     — Prometheus text metrics
"""
from flask import Flask, Response, request, send_file
from pathlib import Path

import structlog

from config import config
from streaming.broadcaster import broadcaster, ICY_METAINT

log = structlog.get_logger(__name__)

app = Flask(__name__)

# ── HTML5 player ──────────────────────────────────────────────────────────────

_CSS_BASE = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Courier New', 'Malgun Gothic', monospace;
    background: #000; color: #fff;
    min-height: 100vh; padding: 3rem 2rem;
    max-width: 760px; margin: 0 auto;
  }
  a { color: #fff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .site-header {
    display: flex; justify-content: space-between; align-items: baseline;
    border-bottom: 1px solid #fff; padding-bottom: 1rem; margin-bottom: 3rem;
  }
  .site-title { font-size: 1rem; letter-spacing: 0.15em; text-transform: uppercase; }
  .site-nav { font-size: 0.75rem; letter-spacing: 0.1em; display: flex; gap: 1.5rem; }
  .site-nav a { opacity: 0.5; }
  .site-nav a:hover, .site-nav a.active { opacity: 1; }
"""

_PLAYER_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NEWSLEADER</title>
  <style>""" + _CSS_BASE + """
    .label {
      font-size: 0.65rem; letter-spacing: 0.2em; text-transform: uppercase;
      opacity: 0.4; margin-bottom: 0.5rem;
    }
    .status-line {
      font-size: 0.75rem; letter-spacing: 0.1em; opacity: 0.5;
      margin-bottom: 2.5rem;
    }
    .now-playing {
      font-size: 0.95rem; line-height: 1.5;
      border-left: 1px solid #fff; padding-left: 1rem;
      margin-bottom: 2.5rem; min-height: 1.5rem;
    }
    audio {
      width: 100%; max-width: 500px;
      filter: invert(1);
      margin-bottom: 0.5rem;
    }
  </style>
</head>
<body>
  <header class="site-header">
    <span class="site-title">Newsleader</span>
    <nav class="site-nav">
      <a href="/" class="active">Live</a>
      <a href="/archive">Archive</a>
    </nav>
  </header>

  <main class="main">
    <p class="label">On Air</p>
    <div class="now-playing" id="now-playing">—</div>

    <p class="label">Stream</p>
    <audio id="radio" controls autoplay>
      <source src="/stream" type="audio/mpeg">
    </audio>
    <p class="status-line" id="status">Connecting...</p>
  </main>

  <script>
  (function() {
    var audio = document.getElementById('radio');
    var statusEl = document.getElementById('status');
    var nowEl = document.getElementById('now-playing');
    var RECONNECT_BASE = 3000, RECONNECT_MAX = 30000;
    var delay = RECONNECT_BASE, timer = null;

    function reconnect() {
      clearTimeout(timer);
      statusEl.textContent = 'Reconnecting...';
      timer = setTimeout(function() {
        audio.src = '/stream?_=' + Date.now();
        audio.load(); audio.play().catch(function(){});
      }, delay);
      delay = Math.min(delay * 2, RECONNECT_MAX);
    }

    audio.addEventListener('playing', function() {
      statusEl.textContent = 'Live  128kbps  MP3';
      delay = RECONNECT_BASE;
    });
    audio.addEventListener('error', function() {
      statusEl.textContent = 'Error — reconnecting';
      reconnect();
    });
    audio.addEventListener('stalled', function() {
      statusEl.textContent = 'Buffering...';
      clearTimeout(timer);
      timer = setTimeout(reconnect, 10000);
    });
    audio.addEventListener('waiting', function() {
      statusEl.textContent = 'Buffering...';
    });

    function pollStatus() {
      fetch('/status').then(function(r){ return r.json(); }).then(function(d) {
        if (d && d.now_playing) nowEl.textContent = d.now_playing;
      }).catch(function(){});
    }
    setInterval(pollStatus, 10000);
    pollStatus();
  })();
  </script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return _PLAYER_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/stream")
def audio_stream():
    """ICY-compatible infinite MP3 stream."""
    client_ip = request.remote_addr
    log.info("stream_request", ip=client_ip)

    # Detect if client wants ICY metadata injection
    want_metadata = request.headers.get("Icy-Metadata", "0").strip() == "1"

    cid, q = broadcaster.add_listener()

    def generate():
        try:
            yield from broadcaster.stream_client(cid, q, want_metadata=want_metadata)
        except Exception as exc:
            log.warning("stream_error", client_id=cid, error=str(exc))
            broadcaster.remove_listener(cid)

    headers = {
        "Content-Type":          "audio/mpeg",
        "Cache-Control":         "no-cache, no-store",
        "Pragma":                "no-cache",
        "X-Content-Type-Options": "nosniff",
        # ICY headers (ASCII only — gunicorn rejects non-ASCII)
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
    m3u = f"#EXTM3U\n#EXTINF:-1,NewsLeader 라디오\nhttp://{host}/stream\n"
    return Response(m3u, mimetype="audio/x-mpegurl",
                    headers={"Content-Disposition": "attachment; filename=listen.m3u"})


_ARCHIVE_ROOT = Path("archive")


@app.route("/archive")
def archive_index():
    """다시 듣기 웹 페이지 (브라우저) / 날짜 목록 JSON (Accept: application/json)."""
    if not _ARCHIVE_ROOT.exists():
        dates = []
    else:
        dates = sorted(
            [d.name for d in _ARCHIVE_ROOT.iterdir() if d.is_dir()],
            reverse=True
        )

    if "application/json" in request.headers.get("Accept", ""):
        return {"dates": dates}, 200

    date_counts = {}
    for d in dates:
        date_counts[d] = len(list((_ARCHIVE_ROOT / d).glob("*.mp3")))

    date_rows = "".join(
        f'<a href="/archive/{d}" class="date-row">'
        f'<span>{d}</span><span class="count">{date_counts[d]}</span>'
        f'</a>'
        for d in dates
    ) or '<p class="empty">저장된 방송이 없습니다.</p>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NEWSLEADER — Archive</title>
  <style>{_CSS_BASE}
    .label {{ font-size: 0.65rem; letter-spacing: 0.2em; text-transform: uppercase;
              opacity: 0.4; margin-bottom: 1rem; }}
    .date-row {{
      display: flex; justify-content: space-between; align-items: center;
      border: 1px solid #333; padding: 0.8rem 1rem;
      margin-bottom: -1px; color: #fff; text-decoration: none;
      font-size: 0.85rem; letter-spacing: 0.05em;
      transition: border-color 0.1s, color 0.1s;
    }}
    .date-row:hover {{ border-color: #fff; z-index: 1; position: relative; }}
    .count {{ opacity: 0.4; font-size: 0.75rem; }}
    .empty {{ opacity: 0.4; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <header class="site-header">
    <span class="site-title">Newsleader</span>
    <nav class="site-nav">
      <a href="/">Live</a>
      <a href="/archive" class="active">Archive</a>
    </nav>
  </header>
  <main class="main">
    <p class="label">Broadcasts by Date</p>
    {date_rows}
  </main>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/archive/<date>")
def archive_date(date: str):
    """특정 날짜 방송 목록 (웹 페이지 + 인라인 플레이어)."""
    if ".." in date:
        return "invalid", 400
    date_dir = _ARCHIVE_ROOT / date
    if not date_dir.exists():
        return "not found", 404

    files = sorted([f.name for f in date_dir.glob("*.mp3")])

    if "application/json" in request.headers.get("Accept", ""):
        return {"date": date, "files": files, "count": len(files)}, 200

    def parse_fn(fn):
        t = fn[:8].replace("-", ":")
        title = fn[9:].replace("_", " ").replace(".mp3", "")
        return t, title

    rows = "".join(
        f'<div class="track" onclick="play(\'/archive/{date}/{fn}\')">'
        f'<span class="time">{parse_fn(fn)[0]}</span>'
        f'<span class="title">{parse_fn(fn)[1]}</span>'
        f'</div>'
        for fn in files
    ) or '<p class="empty">파일이 없습니다.</p>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NEWSLEADER — {date}</title>
  <style>{_CSS_BASE}
    .label {{ font-size: 0.65rem; letter-spacing: 0.2em; text-transform: uppercase;
              opacity: 0.4; margin-bottom: 0.6rem; }}
    .player-bar {{
      border: 1px solid #333; padding: 1rem;
      margin-bottom: 2rem; position: sticky; top: 0; background: #000;
    }}
    .now {{
      font-size: 0.75rem; letter-spacing: 0.05em; opacity: 0.5;
      margin-bottom: 0.6rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .now.playing {{ opacity: 1; }}
    audio {{ width: 100%; filter: invert(1); }}
    .track {{
      display: flex; gap: 1.5rem; align-items: baseline;
      border: 1px solid #222; padding: 0.7rem 1rem;
      margin-bottom: -1px; cursor: pointer;
      transition: border-color 0.1s;
    }}
    .track:hover, .track.active {{ border-color: #fff; z-index: 1; position: relative; }}
    .time {{ font-size: 0.7rem; opacity: 0.4; white-space: nowrap; flex-shrink: 0; }}
    .title {{ font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .meta {{ font-size: 0.75rem; opacity: 0.4; margin-bottom: 2rem; }}
    .empty {{ opacity: 0.4; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <header class="site-header">
    <span class="site-title">Newsleader</span>
    <nav class="site-nav">
      <a href="/">Live</a>
      <a href="/archive" class="active">Archive</a>
    </nav>
  </header>
  <main class="main">
    <div class="player-bar">
      <div class="now" id="now">—</div>
      <audio id="player" controls></audio>
    </div>
    <p class="label">{date}</p>
    <p class="meta">{len(files)} broadcasts</p>
    <div id="list">{rows}</div>
  </main>

  <script>
  var player = document.getElementById('player');
  var nowEl  = document.getElementById('now');
  var active = null;

  function play(src) {{
    var tracks = document.querySelectorAll('.track');
    tracks.forEach(function(t) {{ t.classList.remove('active'); }});
    var track = Array.from(tracks).find(function(t) {{
      return t.getAttribute('onclick').includes(src.split('/').pop());
    }});
    if (track) {{ track.classList.add('active'); active = track; }}
    var title = track ? track.querySelector('.title').textContent : src;
    var time  = track ? track.querySelector('.time').textContent : '';
    nowEl.textContent = time + '  ' + title;
    nowEl.classList.add('playing');
    player.src = src;
    player.play();
  }}

  player.addEventListener('ended', function() {{
    if (!active) return;
    var next = active.nextElementSibling;
    if (next && next.classList.contains('track')) {{
      var src = next.getAttribute('onclick').match(/'([^']+)'/)[1];
      play(src);
    }}
  }});
  </script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/archive/<date>/<filename>")
def archive_file(date: str, filename: str):
    """개별 방송 MP3 스트리밍."""
    if ".." in date or ".." in filename:
        return "invalid", 400
    file_path = _ARCHIVE_ROOT / date / filename
    if not file_path.exists() or file_path.suffix != ".mp3":
        return "not found", 404
    return send_file(file_path, mimetype="audio/mpeg",
                     as_attachment=False,
                     download_name=filename)


def create_app() -> Flask:
    from monitoring.health import register_routes
    register_routes(app)
    return app
