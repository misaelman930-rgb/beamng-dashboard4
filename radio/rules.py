"""
Движок правил автоматизации «если условие → действие». Не зависит от Qt.

Формат правила (JSON):
{
  "name": "Поворотник — приглушить",
  "enabled": true,
  "var": "signal_any",          # переменная из Telemetry.variables()
  "op": ">",                    # > >= < <= == !=
  "value": 0.5,
  "for_s": 0.0,                 # условие должно держаться N секунд
  "action": "duck",             # см. ACTIONS
  "param": 0.4,                 # параметр действия
  "mode": "while",              # while — действует пока условие истинно
                                # once  — срабатывает на фронте (False→True)
  "cooldown_s": 3.0             # пауза между срабатываниями для mode=once
}

Действия:
  duck(param=коэффициент 0..1)    — приглушить громкость (while)
  pause                            — поставить на паузу (while: после снятия — продолжить)
  mute                             — заглушить (while)
  filter(param=0..1)               — добавить силу «радио-фильтра» (while)
  next / prev                      — следующая / предыдущая станция (once)
  genre(param=название жанра)      — переключиться на станцию жанра (once)
  jingle(param=путь к файлу или пусто = встроенный «блип») (once)
  set_volume(param=0..100)         — задать базовую громкость (once)
"""
from __future__ import annotations

import operator
import time
from dataclasses import dataclass
from typing import Callable, Optional

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt,
       "<=": operator.le, "==": operator.eq, "!=": operator.ne}

# Переменные, доступные в условиях (синхронно с Telemetry.variables()).
VARIABLES = [
    "speed_kmh", "rpm", "gear", "fuel", "engine_temp", "oil_temp", "turbo",
    "throttle", "brake", "clutch", "handbrake", "signal_left", "signal_right",
    "signal_any", "fullbeam", "abs", "tc", "oil_warn", "battery_warn",
    "shift_light", "engine_off", "stopped",
]
ACTIONS = ["duck", "pause", "mute", "filter", "next", "prev", "genre",
           "jingle", "set_volume"]
WHILE_ACTIONS = {"duck", "pause", "mute", "filter"}   # поддерживают mode=while


def default_rules() -> list[dict]:
    """Стартовый набор правил (пользователь может править/удалять)."""
    return [
        {"name": "Поворотник: приглушить", "enabled": True,
         "var": "signal_any", "op": ">", "value": 0.5, "for_s": 0.0,
         "action": "duck", "param": 0.45, "mode": "while", "cooldown_s": 0.0},
        {"name": "ABS: приглушить", "enabled": True,
         "var": "abs", "op": ">", "value": 0.5, "for_s": 0.0,
         "action": "duck", "param": 0.3, "mode": "while", "cooldown_s": 0.0},
        {"name": "TC: джингл", "enabled": False,
         "var": "tc", "op": ">", "value": 0.5, "for_s": 0.0,
         "action": "jingle", "param": "", "mode": "once", "cooldown_s": 5.0},
        {"name": "Ручник 30 с: пауза", "enabled": True,
         "var": "handbrake", "op": ">", "value": 0.5, "for_s": 30.0,
         "action": "pause", "param": "", "mode": "while", "cooldown_s": 0.0},
        {"name": "Мотор заглушен 10 с: пауза", "enabled": True,
         "var": "engine_off", "op": ">", "value": 0.5, "for_s": 10.0,
         "action": "pause", "param": "", "mode": "while", "cooldown_s": 0.0},
        {"name": "Низкое топливо: джингл", "enabled": False,
         "var": "fuel", "op": "<", "value": 10, "for_s": 2.0,
         "action": "jingle", "param": "", "mode": "once", "cooldown_s": 60.0},
    ]


@dataclass
class Effects:
    """Суммарный результат всех активных while-правил."""
    duck: float = 1.0       # множитель громкости (минимум по правилам)
    pause: bool = False
    mute: bool = False
    filter_boost: float = 0.0


@dataclass
class _State:
    since: Optional[float] = None   # когда условие стало истинным
    active: bool = False
    last_fire: float = -1e9


class RuleEngine:
    """
    evaluate(vars) вызывается ~10 раз в секунду. Для once-действий вызывает
    колбэк on_action(action, param); для while-действий возвращает Effects.
    """

    def __init__(self, rules: list[dict],
                 on_action: Optional[Callable[[str, object], None]] = None):
        self.on_action = on_action
        self._states: list[_State] = []
        self.set_rules(rules)

    def set_rules(self, rules: list[dict]) -> None:
        self.rules = [dict(r) for r in rules]
        self._states = [_State() for _ in self.rules]

    @staticmethod
    def _check(rule: dict, variables: dict) -> bool:
        if rule.get("var") not in variables:
            return False
        fn = OPS.get(rule.get("op", ">"))
        if fn is None:
            return False
        try:
            return bool(fn(variables[rule["var"]], float(rule.get("value", 0))))
        except (TypeError, ValueError):
            return False

    def evaluate(self, variables: Optional[dict], now: Optional[float] = None) -> Effects:
        """variables=None означает «нет телеметрии»: все правила неактивны."""
        now = time.monotonic() if now is None else now
        fx = Effects()
        for rule, st in zip(self.rules, self._states):
            cond = (variables is not None and rule.get("enabled", True)
                    and self._check(rule, variables))
            if cond:
                if st.since is None:
                    st.since = now
                holds = (now - st.since) >= float(rule.get("for_s", 0) or 0)
            else:
                st.since = None
                holds = False

            action = rule.get("action")
            param = rule.get("param")
            mode = rule.get("mode", "while")
            if action not in WHILE_ACTIONS:
                mode = "once"                     # «разовые» действия всегда по фронту

            if mode == "once":
                # Срабатывание на фронте с учётом cooldown.
                if holds and not st.active:
                    if now - st.last_fire >= float(rule.get("cooldown_s", 0) or 0):
                        st.last_fire = now
                        if self.on_action:
                            self.on_action(action, param)
                st.active = holds
                continue

            st.active = holds
            if not holds:
                continue
            # while-действия складываются в общий Effects.
            if action == "duck":
                fx.duck = min(fx.duck, _clamp(_num(param, 0.5), 0.0, 1.0))
            elif action == "pause":
                fx.pause = True
            elif action == "mute":
                fx.mute = True
            elif action == "filter":
                fx.filter_boost = max(fx.filter_boost, _clamp(_num(param, 0.5), 0.0, 1.0))
        return fx

    def active_rules(self) -> list[str]:
        return [r.get("name", "?") for r, s in zip(self.rules, self._states) if s.active]


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def interp_curve(curve: list, x: float) -> float:
    """
    Линейная интерполяция кривой [[x0, y0], [x1, y1], ...] (точки сортируются).
    Вне диапазона — значение крайней точки. Используется для «громкость от скорости».
    """
    pts = sorted((float(a), float(b)) for a, b in curve)
    if not pts:
        return 1.0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]
