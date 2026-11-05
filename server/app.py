"""
Сервер станций BeamNG Radio.

Что делает:
  * веб-страница (/) — добавить или удалить станцию через браузер;
  * JSON API (/api/stations) — его читает десктопное приложение и подтягивает
    станции автоматически (Настройки → Общие → «Сервер станций»).

Только стандартная библиотека Python 3.11+, поэтому нет зависимостей и сборки.

Переменные окружения:
  PORT         порт (Render задаёт его сам)
  ADMIN_TOKEN  секрет для добавления/удаления. Не задан — запись полностью отключена.
  DATA_FILE    JSON-файл со станциями (по умолчанию data/stations.json)

Запуск локально:  ADMIN_TOKEN=secret python server/app.py
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

log = logging.getLogger("beamng_radio.server")

GENRES = ["rock", "electronic", "phonk", "retro", "jazz", "news", "chanson", "russian", "other"]
MAX_BODY = 8 * 1024          # байт в теле запроса
MAX_STATIONS = 500
URL_MAX = 500
NAME_MAX = 100
ID_RE = re.compile(r"/api/stations/([A-Za-z0-9]{1,32})")


def validate_station(data) -> tuple[Optional[dict], str]:
    """Проверяет и нормализует станцию. Возвращает (станция, '') или (None, код ошибки)."""
    if not isinstance(data, dict):
        return None, "bad_json"
    url = str(data.get("url", "")).strip()
    name = str(data.get("name", "")).strip()[:NAME_MAX]
    genre = str(data.get("genre", "other")).strip().lower()
    if genre not in GENRES:
        genre = "other"
    if not url or len(url) > URL_MAX or any(c.isspace() for c in url):
        return None, "bad_url"
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port                   # бросит ValueError при кривом порте
    except ValueError:
        return None, "bad_url"
    if parts.scheme not in ("http", "https") or not host:
        return None, "bad_url"
    return {"name": name or host, "url": url, "genre": genre}, ""


class Store:
    """Станции в JSON-файле. Запись атомарная, доступ потокобезопасный."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            log.warning("Не удалось прочитать %s, начинаю с пустого списка", self.path)
            return []
        return [i for i in data if isinstance(i, dict) and i.get("id") and i.get("url")]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self.items]

    def add(self, station: dict) -> Optional[dict]:
        with self._lock:
            if len(self.items) >= MAX_STATIONS:
                return None
            item = {"id": uuid.uuid4().hex[:10], **station}
            self.items.append(item)
            self._save()
            return dict(item)

    def remove(self, sid: str) -> bool:
        with self._lock:
            before = len(self.items)
            self.items = [i for i in self.items if i["id"] != sid]
            if len(self.items) == before:
                return False
            self._save()
            return True


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>BeamNG Radio — станции</title>
<style>
:root{--bg:#0c0f14;--panel:#151a22;--line:#2b3543;--text:#e6e9ee;--muted:#7d8795;--acc:#ffb020}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif;padding:16px}
main{max-width:880px;margin:0 auto}
h1{color:var(--acc);font-size:22px;margin:6px 0 16px}
.card{background:var(--panel);border:1px solid #232b37;border-radius:10px;padding:14px;margin-bottom:14px}
input,select,button{font:inherit;background:#1c232d;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:9px}
input,select{width:100%}
label{display:block;color:var(--muted);font-size:13px;margin-bottom:10px}
.row{display:grid;grid-template-columns:2fr 3fr 1fr;gap:8px}
button{cursor:pointer}
button.primary{background:var(--acc);color:#111;border:0;font-weight:bold}
button.danger{color:#ff8a84}
.item{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid #232b37}
.item:last-child{border-bottom:0}
.grow{flex:1;min-width:0}
.name{font-weight:600}
.meta{color:var(--muted);font-size:13px;word-break:break-all}
.tag{color:var(--acc);font-size:12px;text-transform:uppercase;margin-right:6px}
#msg{color:var(--muted);min-height:22px;margin-top:8px}
@media (max-width:640px){.row{grid-template-columns:1fr}}
</style></head>
<body><main>
<h1>BeamNG Radio — станции</h1>
<div class="card">
  <label>Ключ администратора (нужен для добавления и удаления)
    <input id="token" type="password" autocomplete="off">
  </label>
  <form id="form" class="row">
    <input id="name" placeholder="Название" maxlength="100">
    <input id="url" placeholder="https://…/stream.mp3" maxlength="500" required>
    <select id="genre">
      <option>rock</option><option>electronic</option><option>phonk</option>
      <option>retro</option><option>jazz</option><option>news</option>
      <option>chanson</option><option>russian</option><option selected>other</option>
    </select>
    <button class="primary" style="grid-column:1/-1">Добавить станцию</button>
  </form>
  <div id="msg"></div>
</div>
<div class="card" id="list">Загрузка…</div>
</main>
<script>
const $ = id => document.getElementById(id);
const tokenEl = $('token');
tokenEl.value = sessionStorage.getItem('brToken') || '';
tokenEl.addEventListener('input', () => sessionStorage.setItem('brToken', tokenEl.value));

function say(text) { $('msg').textContent = text; }
function auth() { return { 'Authorization': 'Bearer ' + tokenEl.value.trim() }; }

async function load() {
  try {
    const r = await fetch('/api/stations', { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    render((await r.json()).stations);
  } catch (e) {
    $('list').textContent = 'Не удалось загрузить список станций.';
  }
}

function render(items) {
  const box = $('list');
  box.textContent = '';
  if (!items.length) { box.textContent = 'Станций пока нет.'; return; }
  for (const s of items) {
    const row = document.createElement('div');
    row.className = 'item';
    const info = document.createElement('div');
    info.className = 'grow';
    const name = document.createElement('div');
    name.className = 'name';
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = s.genre;
    name.appendChild(tag);
    name.appendChild(document.createTextNode(s.name));
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = s.url;
    info.appendChild(name);
    info.appendChild(meta);
    const del = document.createElement('button');
    del.className = 'danger';
    del.textContent = 'Удалить';
    del.onclick = () => remove(s.id);
    row.appendChild(info);
    row.appendChild(del);
    box.appendChild(row);
  }
}

$('form').addEventListener('submit', async e => {
  e.preventDefault();
  say('Сохраняю…');
  const body = { name: $('name').value, url: $('url').value, genre: $('genre').value };
  try {
    const r = await fetch('/api/stations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...auth() },
      body: JSON.stringify(body)
    });
    const d = await r.json().catch(() => ({}));
    if (r.status === 201) { say('Станция добавлена.'); $('name').value = ''; $('url').value = ''; }
    else say(explain(r.status, d.error));
  } catch (err) { say('Нет связи с сервером.'); }
  load();
});

async function remove(id) {
  if (!confirm('Удалить станцию?')) return;
  const r = await fetch('/api/stations/' + encodeURIComponent(id), { method: 'DELETE', headers: auth() });
  say(r.ok ? 'Станция удалена.' : explain(r.status));
  load();
}

function explain(status, code) {
  if (status === 401) return 'Неверный ключ администратора.';
  if (status === 503) return 'Сервер открыт только для чтения: на нём не задан ADMIN_TOKEN.';
  if (status === 409) return 'Достигнут лимит станций.';
  if (status === 400) return 'Проверьте адрес: нужен http(s):// без пробелов.';
  return 'Ошибка' + (code ? ': ' + code : '') + ' (' + status + ')';
}

load();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "BeamNGRadioServer/1.0"
    # Задаются через make_server():
    store: Store = None  # type: ignore[assignment]
    token: str = ""

    def log_message(self, fmt, *args):      # в логах Render только важное
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---- helpers ----
    def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        if not self.token:
            return False
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:].strip().encode(), self.token.encode())

    def _write_guard(self) -> bool:
        """Для записи: True, если можно продолжать. Иначе ответ уже отправлен."""
        if not self.token:
            self._json(503, {"error": "writes_disabled"})
            return False
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return False
        return True

    # ---- routes ----
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/stations":
            self._json(200, {"stations": self.store.list()})
        elif path == "/healthz":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/stations":
            return self._json(404, {"error": "not_found"})
        if not self._write_guard():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:
            return self._json(400, {"error": "empty_body"})
        if length > MAX_BODY:
            return self._json(413, {"error": "too_large"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "bad_json"})
        station, err = validate_station(data)
        if err:
            return self._json(400, {"error": err})
        added = self.store.add(station)
        if added is None:
            return self._json(409, {"error": "limit"})
        self._json(201, added)

    def do_DELETE(self):
        m = ID_RE.fullmatch(urlsplit(self.path).path)
        if not m:
            return self._json(404, {"error": "not_found"})
        if not self._write_guard():
            return
        if self.store.remove(m.group(1)):
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not_found"})


def make_server(host: str, port: int, data_file: Path, token: str) -> ThreadingHTTPServer:
    """Создаёт HTTP-сервер (port=0 — свободный порт; удобно для тестов)."""
    store = Store(data_file)
    handler = type("BoundHandler", (Handler,), {"store": store, "token": token})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    port = int(os.environ.get("PORT", "8000"))
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    data_file = Path(os.environ.get("DATA_FILE", Path(__file__).resolve().parent.parent / "data" / "stations.json"))
    if not token:
        log.warning("ADMIN_TOKEN не задан: добавление и удаление станций отключены.")
    srv = make_server("0.0.0.0", port, data_file, token)
    log.info("Сервер станций слушает порт %s, данные: %s", port, data_file)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
