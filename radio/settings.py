"""
Хранение настроек в JSON. Файл лежит в %APPDATA%\\BeamNGRadio\\settings.json
(на Linux/macOS — ~/.config/BeamNGRadio) — так настройки переживают обновления .exe.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from pathlib import Path

from .rules import default_rules


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "BeamNGRadio"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS: dict = {
    "language": "ru",                  # "ru" | "en"
    "udp_host": "127.0.0.1",
    "udp_port": 4444,
    "volume": 70,                      # базовая громкость 0..100
    "muted": False,
    "last_station": "",                # id последней станции
    "audio_device": "",                # "" = системное по умолчанию
    "autoplay": False,
    "autoplay_on_engine": True,       # запускать радио / оверлей при запуске двигателя в игре
    "beamng_path": "",                # путь к BeamNG.drive.x64.exe (пусто = автопоиск / Steam)
    "dashboard_port": 8765,           # HTTP-панель для телефона (как SimDashboard)

    # --- громкость от скорости ---
    "speed_volume": {
        "enabled": True,
        # точки кривой: [скорость км/ч, множитель громкости 0..1.5]
        "curve": [[0, 0.45], [50, 0.65], [100, 0.85], [160, 1.0]],
    },
    # --- эффект «радио в машине» ---
    "car_filter": {
        "enabled": True,
        "strength": 0.6,               # общая сила 0..1
        "rpm_max": 7000,               # на этих оборотах эффект максимальный
    },
    # --- автосмена жанра ---
    "auto_genre": {
        "enabled": False,
        "calm_genre": "jazz",
        "energetic_genre": "rock",
        "calm_below_kmh": 40,
        "energetic_above_kmh": 110,
        "min_interval_s": 90,          # не чаще раза в N секунд
    },
    "rules": default_rules(),
    # --- сервер станций (server/app.py): пустой url = не используется ---
    "remote": {"url": "", "interval_s": 300},

    # --- глобальные горячие клавиши (формат pynput) ---
    "hotkeys": {
        "play_pause": "<ctrl>+<alt>+p",
        "next": "<ctrl>+<alt>+<right>",
        "prev": "<ctrl>+<alt>+<left>",
        "vol_up": "<ctrl>+<alt>+<up>",
        "vol_down": "<ctrl>+<alt>+<down>",
        "mute": "<ctrl>+<alt>+m",
        "overlay": "<ctrl>+<alt>+o",
        "click_through": "<ctrl>+<alt>+t",
    },
    # --- оверлей ---
    "overlay": {
        "visible": False,
        "click_through": False,
        "x": 40, "y": 40,
        "opacity": 0.85,
    },
    "window": {"w": 980, "h": 640},
    "car_profiles": {},               # максимумы шкал по машинам (см. car_profile.py)
}


def _merge(base: dict, extra: dict) -> dict:
    """Рекурсивно накладывает extra на base (новые ключи по умолчанию сохраняются)."""
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Потокобезопасный доступ к настройкам с автосохранением."""

    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "settings.json")
        self._lock = threading.RLock()
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError):
            # Битый файл: сохраняем копию и стартуем с настройками по умолчанию.
            try:
                os.replace(self.path, str(self.path) + ".broken")
            except OSError:
                pass

    def save(self) -> None:
        with self._lock:
            tmp = str(self.path) + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)     # атомарная запись
            except OSError:
                pass

    def __getitem__(self, key):
        with self._lock:
            return self.data[key]

    def __setitem__(self, key, value):
        with self._lock:
            self.data[key] = value

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def __contains__(self, key):
        with self._lock:
            return key in self.data
