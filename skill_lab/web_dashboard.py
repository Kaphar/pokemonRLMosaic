"""Small browser dashboard for live map + stats in the skill lab."""

from __future__ import annotations

import json
import struct
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_IMAGE_PATH = (
    PROJECT_ROOT
    / "visualization"
    / "poke_map"
    / "pokemap_full_calibrated_CROPPED_1.png"
)

try:
    from v2.global_map import GLOBAL_MAP_SHAPE
except Exception:
    GLOBAL_MAP_SHAPE = (464, 436)


class BrowserMapDashboard:
    """Simple browser dashboard served locally with a live map and table."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._browser_opened = False
        self.map_width, self.map_height = self._read_map_size()
        self.state: dict[str, Any] = {
            "title": "Skill Lab Dashboard",
            "envs": [],
            "lava_zones": [],
            "last_updated": 0.0,
        }

    def _read_map_size(self) -> tuple[int, int]:
        """Read PNG dimensions without requiring an image-processing package."""
        if MAP_IMAGE_PATH.exists():
            with MAP_IMAGE_PATH.open("rb") as image_file:
                header = image_file.read(24)
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", header[16:24])
        return GLOBAL_MAP_SHAPE[1], GLOBAL_MAP_SHAPE[0]

    def start(self) -> None:
        if self._server is not None:
            return
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.dashboard = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def open_browser(self) -> None:
        if self._browser_opened:
            return
        self._browser_opened = True
        with suppress(Exception):
            webbrowser.open(self.url, new=2)

    def update_state(self, env, env_count: int, *, scores: list[float] | None = None) -> None:
        entries: list[dict[str, Any]] = []
        for idx in range(env_count):
            try:
                hp = float(env.get_attr("read_hp_fraction")[idx]())
                pcount = int(env.get_attr("read_m")[idx](0xD163))
                trainer_wins = int(env.get_attr("trainer_wins")[idx])
                wild_wins = int(env.get_attr("wild_wins")[idx])
                wall_collisions = int(env.get_attr("wall_collisions")[idx])
                steps = int(env.get_attr("step_count")[idx])
                current_map_id = int(env.get_attr("current_map_id")[idx])
                x_pos = int(env.envs[idx].pyboy.memory[0xD362])
                y_pos = int(env.envs[idx].pyboy.memory[0xD361])
                map_n = int(env.envs[idx].pyboy.memory[0xD35E])
                try:
                    gx, gy = self._project_position(x_pos, y_pos, map_n)
                except Exception:
                    gx, gy = 0, 0
            except Exception:
                hp = 0.0
                pcount = 0
                trainer_wins = 0
                wild_wins = 0
                wall_collisions = 0
                steps = 0
                current_map_id = 0
                gx = 0
                gy = 0
            score = float(scores[idx]) if scores is not None and idx < len(scores) else 0.0
            entries.append(
                {
                    "env_index": idx,
                    "hp": hp,
                    "pkmn": pcount,
                    "trainer_wins": trainer_wins,
                    "wild_wins": wild_wins,
                    "walls": wall_collisions,
                    "steps": steps,
                    "map_id": current_map_id,
                    "score": score,
                    "x": gx,
                    "y": gy,
                }
            )
        with self._lock:
            self.state["envs"] = entries
            self.state["last_updated"] = __import__("time").time()

    @staticmethod
    def _project_position(x_pos: int, y_pos: int, map_n: int) -> tuple[int, int]:
        """Convert game coordinates to the stitched map's pixel coordinates."""
        # These offsets match the original BetterMapVis calibration: each game
        # tile is 16 pixels and the map image's origin is at (864, 331).
        map_offsets = {
            0: (0, 0), 1: (-10, 72), 2: (-10, 180),
            12: (0, 36), 13: (0, 144), 14: (30, 172),
            15: (80, 190), 33: (-50, 64), 37: (-9, 2),
            38: (-9, -7), 39: (21, 2), 40: (21, -6),
            41: (30, 47), 42: (30, 55), 43: (30, 72),
            44: (30, 64), 47: (21, 136), 49: (21, 108),
            50: (21, 108), 51: (-35, 137), 52: (-10, 189),
            53: (-10, 198), 54: (-21, 169), 55: (-19, 177),
            56: (-30, 163), 57: (-19, 177), 58: (-25, 154),
            59: (83, 227), 60: (123, 227), 61: (152, 227),
            68: (65, 190),
        }
        offset_x, offset_y = map_offsets.get(map_n, (0, 0))
        pixel_x = 864 + 16 * (offset_x + x_pos)
        pixel_y = 4000 - (331 + 16 * (offset_y + y_pos))
        return int(pixel_x), int(pixel_y)

    def add_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            existing = self.state["lava_zones"]
            if zone not in existing:
                existing.append(zone)

    def remove_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            self.state["lava_zones"] = [z for z in self.state["lava_zones"] if z != zone]

    def toggle_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            current = self.state["lava_zones"]
            if zone in current:
                self.state["lava_zones"] = [z for z in current if z != zone]
            else:
                current.append(zone)

    def _build_handler(self):
        dashboard = self

        class DashboardHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html()
                    return
                if parsed.path == "/api/state":
                    data = json.dumps(dashboard.state).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if parsed.path == "/map.png":
                    self._send_map_image()
                    return
                self.send_error(404)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/api/lava":
                    self.send_error(404)
                    return
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    self.send_error(400, "invalid json")
                    return
                x = int(payload.get("x", 0))
                y = int(payload.get("y", 0))
                dashboard.toggle_lava_zone(x, y)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "lava_zones": dashboard.state["lava_zones"]}).encode("utf-8"))

            def _send_map_image(self) -> None:
                if not MAP_IMAGE_PATH.exists():
                    self.send_error(404, "map image not found")
                    return
                content = MAP_IMAGE_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _send_html(self) -> None:
                svg_w, svg_h = dashboard.map_width, dashboard.map_height
                html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Skill Lab Dashboard</title>
  <style>
    :root {{
      --bg: #0c1220;
      --panel: #141d2e;
      --muted: #8aa0c7;
      --accent: #6ee7ff;
      --good: #67f39b;
      --warning: #ffd166;
      --danger: #ff6b6b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: #eef4ff;
      min-height: 100vh;
    }}
    .tab-bar {{
      display: flex; gap: 4px; padding: 4px 16px; background: rgba(15, 22, 34, 0.96); border-bottom: 1px solid rgba(255,255,255,0.08);
    }}
    .tab-bar .tab-btn {{
      padding: 10px 20px; border-radius: 8px 8px 0 0; border: 1px solid rgba(255,255,255,0.1);
      background: rgba(255,255,255,0.04); color: var(--muted); font-size: 0.9rem; font-weight: 600;
      cursor: pointer; transition: all 0.15s ease;
    }}
    .tab-bar .tab-btn:hover {{ background: rgba(255,255,255,0.08); }}
    .tab-bar .tab-btn.active {{ background: var(--panel); color: var(--accent); border-bottom: 2px solid var(--accent); }}
    .tab-content {{ padding: 18px; height: calc(100vh - 120px); }}
    .tab-pane {{ display: none; height: 100%; }}
    .tab-pane.active {{ display: block; }}
    .panel {{ background: rgba(20, 29, 46, 0.9); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; overflow: hidden; }}
    .map-panel {{ position: relative; display: flex; flex-direction: column; height: 100%; }}
    .header {{ padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.08); display: flex; justify-content: space-between; align-items: center; }}
    .title {{ font-size: 1.05rem; font-weight: 700; }}
    .badge {{ color: var(--accent); font-size: 0.8rem; font-weight: 600; }}
    .map-wrap {{ flex: 1; padding: 12px; position: relative; }}
    .map-wrap svg {{ width: 100%; height: 100%; background: linear-gradient(180deg, #0d1728, #111c2e); border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); cursor: grab; touch-action: none; }}
    .map-wrap svg.grabbing {{ cursor: grabbing; }}
    .zoom-controls {{ position: absolute; right: 14px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column; gap: 6px; z-index: 10; }}
    .zoom-controls button {{ width: 36px; height: 36px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.15); background: rgba(15, 22, 34, 0.85); color: #eef4ff; font-size: 1.1rem; font-weight: 700; cursor: pointer; transition: all 0.15s ease; }}
    .zoom-controls button:hover {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
    .meta {{ color: var(--muted); font-size: 0.75rem; padding: 8px 12px; border-top: 1px solid rgba(255,255,255,0.08); }}
    .stats-panel {{ display: flex; flex-direction: column; height: 100%; }}
    .stats-scroll {{ flex: 1; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; font-size: 0.85rem; }}
    th {{ position: sticky; top: 0; background: rgba(15, 22, 34, 0.98); color: var(--accent); }}
    tbody tr:nth-child(odd) {{ background: rgba(255,255,255,0.01); }}
    .chip {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 700; }}
    .chip.good {{ background: rgba(103, 243, 155, 0.2); color: var(--good); }}
    .chip.warn {{ background: rgba(255, 209, 102, 0.2); color: var(--warning); }}
    .chip.bad {{ background: rgba(255, 107, 107, 0.2); color: var(--danger); }}
  </style>
</head>
<body>
  <div class="tab-bar">
    <button class="tab-btn active" data-tab="map-tab">Map</button>
    <button class="tab-btn" data-tab="stats-tab">Environment Stats</button>
  </div>
  <div class="tab-content">
    <div id="map-tab" class="tab-pane active">
      <div class="panel map-panel">
        <div class="header">
          <div class="title">Live map</div>
          <div class="badge" id="status">waiting…</div>
        </div>
        <div class="map-wrap">
          <svg id="map" viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMidYMid meet">
            <g id="map-zoom-group">
              <image href="/map.png" x="0" y="0" width="{svg_w}" height="{svg_h}" preserveAspectRatio="none" />
              <g id="lava-layer"></g>
              <g id="env-layer"></g>
            </g>
          </svg>
          <div class="zoom-controls">
            <button id="zoom-in" title="Zoom in (+)">+</button>
            <button id="zoom-reset" title="Reset zoom">R</button>
            <button id="zoom-out" title="Zoom out (-)">-</button>
          </div>
        </div>
        <div class="meta">Scroll to zoom, drag to pan. Click a highlighted cell to toggle a lava zone penalty.</div>
      </div>
    </div>
    <div id="stats-tab" class="tab-pane">
      <div class="panel stats-panel">
        <div class="header">
          <div class="title">Live environment stats</div>
          <div class="badge"><span id="env-count">0</span> envs</div>
        </div>
        <div class="stats-scroll">
          <table>
            <thead>
              <tr>
                <th>Env</th>
                <th>HP</th>
                <th>Pokémon</th>
                <th>Trainer Wins</th>
                <th>Wild Wins</th>
                <th>Walls</th>
                <th>Steps</th>
                <th>Map</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody id="stats-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script>
    const mapSvg = document.getElementById('map');
    const envLayer = document.getElementById('env-layer');
    const lavaLayer = document.getElementById('lava-layer');
    const statsBody = document.getElementById('stats-body');
    const envCount = document.getElementById('env-count');
    const status = document.getElementById('status');
    const zoomInBtn = document.getElementById('zoom-in');
    const zoomOutBtn = document.getElementById('zoom-out');
    const zoomResetBtn = document.getElementById('zoom-reset');
    const tabBtns = document.querySelectorAll('.tab-bar .tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    let zoomScale = 1;
    let panX = 0;
    let panY = 0;
    let isPanning = false;
    let panStart = {{ x: 0, y: 0 }};
    const mapGroup = document.getElementById('map-zoom-group');

    function applyTransform() {{
      mapGroup.setAttribute('transform', 'translate(' + panX + ',' + panY + ') scale(' + zoomScale + ')');
    }}

    function setZoom(delta) {{
      const newScale = zoomScale * delta;
      if (newScale < 0.4 || newScale > 8) return;
      zoomScale = newScale;
      applyTransform();
    }}

    function resetZoom() {{
      zoomScale = 1;
      panX = 0;
      panY = 0;
      applyTransform();
    }}

    function hpChip(value) {{
      const label = (value * 100).toFixed(0) + '%';
      if (value >= 0.6) return '<span class="chip good">' + label + '</span>';
      if (value >= 0.25) return '<span class="chip warn">' + label + '</span>';
      return '<span class="chip bad">' + label + '</span>';
    }}

    function renderMap(data) {{
      envLayer.innerHTML = '';
      lavaLayer.innerHTML = '';
      const lavaZones = data.lava_zones || [];
      for (const zone of lavaZones) {{
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', zone[0] - 2);
        rect.setAttribute('y', zone[1] - 2);
        rect.setAttribute('width', 8);
        rect.setAttribute('height', 8);
        rect.setAttribute('fill', '#ff6b6b');
        rect.setAttribute('opacity', '0.8');
        lavaLayer.appendChild(rect);
      }}

      for (const env of data.envs || []) {{
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', env.x);
        circle.setAttribute('cy', env.y);
        circle.setAttribute('r', 6);
        circle.setAttribute('fill', '#67f39b');
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', 1.2);
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', env.x + 10);
        label.setAttribute('y', env.y - 8);
        label.setAttribute('fill', '#eaf2ff');
        label.setAttribute('font-size', '12');
        label.textContent = 'E' + (env.env_index + 1);
        envLayer.appendChild(circle);
        envLayer.appendChild(label);
      }}
    }}

    function renderStats(data) {{
      const envs = data.envs || [];
      statsBody.innerHTML = envs.map(function(env) {{
        var hpHtml = hpChip(env.hp);
        var scoreText = (env.score >= 0 ? '+' : '') + env.score.toFixed(1);
        return '<tr><td>Env ' + (env.env_index + 1) + '</td><td>' + hpHtml + '</td><td>' + env.pkmn + '</td><td>' + env.trainer_wins + '</td><td>' + env.wild_wins + '</td><td>' + env.walls + '</td><td>' + env.steps + '</td><td>' + env.map_id.toString(16).toUpperCase().padStart(2, '0') + '</td><td>' + scoreText + '</td></tr>';
      }}).join('');
      envCount.textContent = String(envs.length);
    }}

    function update() {{
      fetch('/api/state')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          if (!data || !Array.isArray(data.envs)) return;
          status.textContent = 'live';
          renderMap(data);
          renderStats(data);
        }})
        .catch(function() {{
          status.textContent = 'offline';
        }});
    }}

    mapSvg.addEventListener('wheel', function(event) {{
      event.preventDefault();
      event.stopPropagation();
      const delta = event.deltaY < 0 ? 1.15 : 0.85;
      setZoom(delta);
    }}, {{ passive: false }});

    mapSvg.addEventListener('mousedown', function(event) {{
      isPanning = true;
      panStart = {{ x: event.clientX, y: event.clientY }};
      mapSvg.classList.add('grabbing');
    }});

    document.addEventListener('mousemove', function(event) {{
      if (!isPanning) return;
      const dx = event.clientX - panStart.x;
      const dy = event.clientY - panStart.y;
      panX += dx;
      panY += dy;
      panStart = {{ x: event.clientX, y: event.clientY }};
      applyTransform();
    }});

    document.addEventListener('mouseup', function(event) {{
      if (!isPanning) return;
      isPanning = false;
      mapSvg.classList.remove('grabbing');
    }});

    document.addEventListener('keydown', function(event) {{
      if (isMapTabActive() && (event.key === '+' || event.key === '-' || event.key === '=')) {{
        event.preventDefault();
        if (event.key === '+' || event.key === '=') {{
          setZoom(1.15);
        }} else {{
          setZoom(0.85);
        }}
      }}
      if (isMapTabActive() && event.key === 'r' && (event.ctrlKey || event.metaKey)) {{
        event.preventDefault();
        resetZoom();
      }}
    }});

    function isMapTabActive() {{
      return document.getElementById('map-tab').classList.contains('active');
    }}

    zoomInBtn.addEventListener('click', function() {{ setZoom(1.15); }});
    zoomOutBtn.addEventListener('click', function() {{ setZoom(0.85); }});
    zoomResetBtn.addEventListener('click', function() {{ resetZoom(); }});

    mapSvg.addEventListener('click', function(event) {{
      const rect = mapSvg.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * {svg_w};
      const y = ((event.clientY - rect.top) / rect.height) * {svg_h};
      fetch('/api/lava', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ x: Math.round(x), y: Math.round(y) }})
      }}).catch(function() {{}});
    }});

    tabBtns.forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        tabBtns.forEach(function(b) {{ b.classList.remove('active'); }});
        tabPanes.forEach(function(p) {{ p.classList.remove('active'); }});
        btn.classList.add('active');
        const target = btn.getAttribute('data-tab');
        document.getElementById(target).classList.add('active');
      }});
    }});

    update();
    setInterval(update, 500);
  </script>
</body>
</html>
""".format(svg_w=svg_w, svg_h=svg_h)
                encoded = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return DashboardHandler


def main() -> None:
    dashboard = BrowserMapDashboard()
    dashboard.start()
    print(f"[Dashboard] Live map + stats: {dashboard.url}")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        dashboard.stop()


if __name__ == "__main__":
    main()
