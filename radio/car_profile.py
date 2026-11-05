"""
Подстройка шкал приборов под машину.

Максимум скорости — до 320 км/ч (потолок). Максимум оборотов в пакетах OutGauge
не передаётся, поэтому он «выучивается»: шкала растёт, когда машина показывает
более высокие значения. Профили хранятся в настройках по имени машины.
"""
from __future__ import annotations

import math

SPEED_CAP = 320.0          # потолок шкалы скорости, км/ч
SPEED_START = 200.0        # стартовая шкала, пока машина не ехала быстрее
RPM_START = 7000.0
RPM_CAP = 20000.0


def _ceil_to(value: float, step: float) -> float:
    return math.ceil(value / step) * step


def default_profile() -> dict:
    return {"max_kmh": SPEED_START, "max_rpm": RPM_START}


def _key(car: str) -> str:
    return (car or "").strip() or "default"


def learn(profiles: dict, car: str, kmh: float, rpm: float) -> bool:
    """Расширяет шкалы профиля машины. Возвращает True, если профиль изменился."""
    key = _key(car)
    prof = profiles.setdefault(key, default_profile())
    changed = False
    if kmh > prof["max_kmh"] * 0.97 and prof["max_kmh"] < SPEED_CAP:
        new = min(SPEED_CAP, _ceil_to(kmh * 1.1, 20))
        if new > prof["max_kmh"]:
            prof["max_kmh"] = new
            changed = True
    if rpm > prof["max_rpm"] * 0.97:
        new = min(RPM_CAP, _ceil_to(rpm * 1.05, 500))
        if new > prof["max_rpm"]:
            prof["max_rpm"] = new
            changed = True
    return changed


def scale_for(profiles: dict, car: str) -> dict:
    """Шкалы для интерфейса: {'max_kmh', 'max_rpm', 'car'}."""
    key = _key(car)
    prof = profiles.get(key) or default_profile()
    return {"max_kmh": float(prof["max_kmh"]), "max_rpm": float(prof["max_rpm"]), "car": key}
