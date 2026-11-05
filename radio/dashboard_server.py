"""
Веб-приборная панель для телефона (классический кластер + API).

ПК поднимает HTTP на порту 8765.
Телефон: http://<IP_ПК>:8765 — тахометр, спидометр, топливо, температура.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from . import car_profile
from .telemetry import DL_BATTERY, DL_OILWARN

if TYPE_CHECKING:
    from .controller import Controller

log = logging.getLogger("beamng_radio.dashboard")

DEFAULT_PORT = 8765


def _local_ips() -> list:
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_page(name: str) -> str:
    try:
        return (STATIC_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return ("<html><body style='background:#000;color:#fff;padding:2rem;font-family:sans-serif'>"
                f"Файл {name} не найден: проверьте, что сборка включает папку static.</body></html>")


DASHBOARD_HTML = _load_page("cluster.html")     # круглые приборы (canvas)
DIGITAL_HTML = _load_page("digital.html")       # цифровой вид, без canvas

# Файлы для установки на телефон (PWA): только эти пути, без произвольного доступа к папке.
STATIC_FILES = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}


class _Handler(BaseHTTPRequestHandler):
    controller = None

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        name, ctype = STATIC_FILES[path]
        try:
            body = (STATIC_DIR / name).read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard"):
            self._html(DASHBOARD_HTML)
            return
        if path in ("/digital", "/digital.html"):
            self._html(DIGITAL_HTML)
            return
        if path in STATIC_FILES:
            self._static(path)
            return
        if path == "/api/state":
            self._json(200, self._state())
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/cmd":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(min(length, 4096)) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad_json"})
            return
        ok = self._cmd(data)
        self._json(200, {"ok": ok})

    def _state(self):
        c = self.controller
        if not c:
            return {"connected": False, "stations": []}
        t = c.last_telemetry
        tel = None
        if t:
            tel = {
                "speed_kmh": t.speed_kmh,
                "rpm": t.rpm,
                "gear": t.gear,
                "fuel": t.fuel,
                "engine_temp": t.engine_temp,
                "turbo": t.turbo,
                "throttle": t.throttle,
                "brake": t.brake,
                "handbrake": t.handbrake,
                "signal_left": t.signal_left,
                "signal_right": t.signal_right,
                "abs": t.abs_active,
                "fullbeam": t.fullbeam,
                "battery": t.light(DL_BATTERY),
                "oil": t.light(DL_OILWARN),
                "tc": t.tc_active,
            }
        stations = [
            {"id": s.id, "name": s.name, "favorite": s.favorite}
            for s in c.store.stations if s.playable
        ]
        st = c.current
        playing = False
        if c.audio:
            playing = c.audio.status() in ("playing", "buffering", "retrying")
        return {
            "connected": bool(c.connected),
            "telemetry": tel,
            "station": st.name if st else "",
            "station_id": st.id if st else "",
            "track": c.now_track,
            "scale": car_profile.scale_for(c.car_profiles, t.car if t else ""),
            "playing": playing,
            "volume": int(c.settings["volume"]),
            "muted": bool(c.settings["muted"]),
            "stations": stations,
        }

    def _cmd(self, data):
        c = self.controller
        if not c:
            return False
        action = str(data.get("action", ""))
        try:
            if action == "play":
                c.toggle_play()
            elif action == "next":
                c.next_station()
            elif action == "prev":
                c.prev_station()
            elif action == "mute":
                c.toggle_mute()
            elif action == "volume":
                c.set_volume(int(data.get("value", 70)))
            elif action == "play_station":
                sid = str(data.get("id", ""))
                if sid:
                    c.play_station(sid)
            else:
                return False
            return True
        except Exception:
            log.exception("dashboard cmd failed")
            return False


class DashboardServer:
    def __init__(self, controller, port=DEFAULT_PORT):
        self.controller = controller
        self.port = port
        self._httpd = None
        self._thread = None
        self.urls = []

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        handler = type("DashHandler", (_Handler,), {"controller": self.controller})
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        except OSError as e:
            log.warning("Dashboard port %s busy: %s", self.port, e)
            for p in range(self.port + 1, self.port + 10):
                try:
                    self._httpd = ThreadingHTTPServer(("0.0.0.0", p), handler)
                    self.port = p
                    break
                except OSError:
                    continue
            if not self._httpd:
                log.error("Could not bind dashboard server")
                return
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="DashboardHTTP"
        )
        self._thread.start()
        self.urls = ["http://%s:%s" % (ip, self.port) for ip in _local_ips()]
        log.info("Dashboard: %s", ", ".join(self.urls))

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
