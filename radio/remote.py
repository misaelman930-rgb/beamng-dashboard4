"""
Клиент сервера станций: периодически забирает список из server/app.py.

Только стандартная библиотека. Ошибки сети не роняют приложение: результат
отдаётся колбэком (items, error), а дальше решает контроллер.
"""
from __future__ import annotations

import json
import threading
from typing import Callable, Optional
from urllib.request import Request, urlopen

from .stations import GENRES

MAX_RESPONSE = 256 * 1024          # защита от слишком большого ответа
MAX_ITEMS = 500


def normalize_server_url(base: str) -> str:
    """Пустая строка — сервер не используется. Иначе нужен http(s)://."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("URL сервера должен начинаться с http:// или https://")
    return base


def fetch_stations(base: str, timeout: float = 6.0) -> list[dict]:
    """Возвращает нормализованный список станций с сервера. Бросает OSError/ValueError."""
    url = normalize_server_url(base) + "/api/stations"
    req = Request(url, headers={"User-Agent": "BeamNGRadio/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:          # HTTPError и URLError — подклассы OSError
        raw = resp.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("ответ сервера слишком большой")
    data = json.loads(raw.decode("utf-8"))
    out: list[dict] = []
    for it in (data.get("stations") or [])[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("id", "")).strip()
        url_s = str(it.get("url", "")).strip()
        if not sid or not url_s.lower().startswith(("http://", "https://")):
            continue
        genre = str(it.get("genre", "other"))
        out.append({
            "id": sid,
            "name": str(it.get("name", "")).strip()[:100] or url_s,
            "url": url_s,
            "genre": genre if genre in GENRES else "other",
        })
    return out


class RemoteSync(threading.Thread):
    """Фоновый опрос сервера. on_result(items | None, error_text)."""

    def __init__(self, base: str, interval_s: float,
                 on_result: Callable[[Optional[list], str], None]):
        super().__init__(daemon=True, name="StationsSync")
        self.base = base
        self.interval = max(30.0, float(interval_s))
        self.on_result = on_result
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.on_result(fetch_stations(self.base), "")
            except (OSError, ValueError) as e:
                self.on_result(None, str(e))
            self._stop_evt.wait(self.interval)
