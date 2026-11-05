"""
Телеметрия BeamNG.drive по протоколу OutGauge (UDP).

Формат пакета (как в Live for Speed / InSim), little-endian, без выравнивания:

    unsigned Time        # время в мс (в BeamNG не используется)
    char     Car[4]      # имя машины
    word     Flags       # OG_SHIFT=1, OG_CTRL=2, OG_TURBO=8192, OG_KM=16384, OG_BAR=32768
    char     Gear        # 0 = задняя, 1 = нейтраль, 2 = первая ...
    char     PLID
    float    Speed       # м/с
    float    RPM
    float    Turbo       # бар
    float    EngTemp     # °C
    float    Fuel        # 0..1
    float    OilPressure # бар
    float    OilTemp     # °C
    unsigned DashLights  # какие лампы вообще есть у машины
    unsigned ShowLights  # какие лампы горят сейчас
    float    Throttle    # 0..1
    float    Brake       # 0..1
    float    Clutch      # 0..1
    char     Display1[16]
    char     Display2[16]
    int      ID          # необязательное поле (пакет 96 байт вместо 92)

Модуль не зависит от Qt: класс TelemetryListener работает в своём потоке
и вызывает колбэки, а UI подписывается на них через сигналы-обёртки.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# --- Битовые маски ламп (DL_*) из документации LFS/OutGauge ---------------
DL_SHIFT = 1 << 0        # индикатор переключения передачи
DL_FULLBEAM = 1 << 1     # дальний свет
DL_HANDBRAKE = 1 << 2    # ручник
DL_PITSPEED = 1 << 3     # ограничитель скорости в питах
DL_TC = 1 << 4           # TC (контроль тяги)
DL_SIGNAL_L = 1 << 5     # левый поворотник
DL_SIGNAL_R = 1 << 6     # правый поворотник
DL_SIGNAL_ANY = 1 << 7   # аварийка
DL_OILWARN = 1 << 8      # давление масла
DL_BATTERY = 1 << 9      # аккумулятор
DL_ABS = 1 << 10         # ABS

# Размеры пакета: 92 байта без ID, 96 с ID.
_FMT = "<I4sHBBfffffffIIfff16s16s"
PACKET_SIZE = struct.calcsize(_FMT)  # 92
assert PACKET_SIZE == 92


@dataclass
class Telemetry:
    """Разобранный пакет + удобные производные величины."""
    car: str = ""
    gear: int = 1                 # 0=R, 1=N, 2=1-я ...
    speed_ms: float = 0.0
    rpm: float = 0.0
    turbo: float = 0.0
    engine_temp: float = 0.0
    fuel: float = 0.0
    oil_pressure: float = 0.0
    oil_temp: float = 0.0
    dash_lights: int = 0
    show_lights: int = 0
    throttle: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    # ---- производные ----
    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6

    def light(self, mask: int) -> bool:
        return bool(self.show_lights & mask)

    @property
    def handbrake(self) -> bool:
        return self.light(DL_HANDBRAKE)

    @property
    def signal_left(self) -> bool:
        return self.light(DL_SIGNAL_L)

    @property
    def signal_right(self) -> bool:
        return self.light(DL_SIGNAL_R)

    @property
    def signal_any(self) -> bool:
        return self.light(DL_SIGNAL_L | DL_SIGNAL_R | DL_SIGNAL_ANY)

    @property
    def abs_active(self) -> bool:
        return self.light(DL_ABS)

    @property
    def tc_active(self) -> bool:
        return self.light(DL_TC)

    @property
    def fullbeam(self) -> bool:
        return self.light(DL_FULLBEAM)

    @property
    def engine_off(self) -> bool:
        # В BeamNG при заглушенном моторе обороты падают до ~0.
        return self.rpm < 50.0

    @property
    def stopped(self) -> bool:
        return self.speed_kmh < 1.0

    def variables(self) -> dict:
        """Словарь переменных для движка правил (см. rules.py)."""
        return {
            "speed_kmh": self.speed_kmh,
            "rpm": self.rpm,
            "gear": float(self.gear),
            "fuel": self.fuel * 100.0,
            "engine_temp": self.engine_temp,
            "oil_temp": self.oil_temp,
            "turbo": self.turbo,
            "throttle": self.throttle * 100.0,
            "brake": self.brake * 100.0,
            "clutch": self.clutch * 100.0,
            "handbrake": float(self.handbrake),
            "signal_left": float(self.signal_left),
            "signal_right": float(self.signal_right),
            "signal_any": float(self.signal_any),
            "fullbeam": float(self.fullbeam),
            "abs": float(self.abs_active),
            "tc": float(self.tc_active),
            "oil_warn": float(self.light(DL_OILWARN)),
            "battery_warn": float(self.light(DL_BATTERY)),
            "shift_light": float(self.light(DL_SHIFT)),
            "engine_off": float(self.engine_off),
            "stopped": float(self.stopped),
        }


def parse_packet(data: bytes) -> Optional[Telemetry]:
    """Разбирает UDP-пакет OutGauge. Возвращает None, если пакет повреждён."""
    if len(data) < PACKET_SIZE:
        return None
    try:
        (_time, car, _flags, gear, _plid, speed, rpm, turbo, eng_temp, fuel,
         oil_p, oil_t, dash, show, thr, brk, clu, _d1, _d2) = struct.unpack(
            _FMT, data[:PACKET_SIZE])
    except struct.error:
        return None
    # Защита от мусора (NaN/inf, нереальные значения).
    for v in (speed, rpm, turbo, eng_temp, fuel, thr, brk, clu):
        if v != v or abs(v) > 1e7:
            return None
    return Telemetry(
        car=car.split(b"\0", 1)[0].decode("ascii", "ignore"),
        gear=gear, speed_ms=speed, rpm=rpm, turbo=turbo, engine_temp=eng_temp,
        fuel=fuel, oil_pressure=oil_p, oil_temp=oil_t, dash_lights=dash,
        show_lights=show, throttle=thr, brake=brk, clutch=clu)


def build_packet(t: Telemetry, packet_id: int = 0, with_id: bool = True) -> bytes:
    """Собирает пакет OutGauge (нужен эмулятору и тестам)."""
    raw = struct.pack(
        _FMT, int(time.time() * 1000) & 0xFFFFFFFF, t.car.encode("ascii")[:4],
        0, max(0, min(255, t.gear)), 0, t.speed_ms, t.rpm, t.turbo,
        t.engine_temp, t.fuel, t.oil_pressure, t.oil_temp, t.dash_lights,
        t.show_lights, t.throttle, t.brake, t.clutch, b"", b"")
    return raw + struct.pack("<i", packet_id) if with_id else raw


class TelemetryListener(threading.Thread):
    """
    Поток, слушающий UDP-порт OutGauge.

    Состояния подключения:
      * connected=False — пакетов нет дольше `timeout` секунд («Ожидание игры»);
      * connected=True  — пакеты идут.
    Если порт занят или сокет сломался, поток пересоздаёт сокет каждые 2 с —
    так работает автопереподключение при перезапуске игры/смене порта.
    """

    def __init__(self, port: int = 4444, host: str = "127.0.0.1",
                 timeout: float = 2.0,
                 on_data: Optional[Callable[[Telemetry], None]] = None,
                 on_status: Optional[Callable[[bool, str], None]] = None):
        super().__init__(daemon=True, name="OutGaugeListener")
        self.port = port
        self.host = host
        self.timeout = timeout
        self.on_data = on_data
        self.on_status = on_status
        self.connected = False
        self.last: Optional[Telemetry] = None
        self.lost_packets = 0          # грубая оценка потерь по ID пакета
        self._last_id: Optional[int] = None
        self._stop_evt = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._restart = threading.Event()

    # ---- управление ----
    def set_port(self, port: int) -> None:
        """Смена порта на лету: сокет будет пересоздан."""
        self.port = port
        self._restart.set()

    def stop(self) -> None:
        self._stop_evt.set()
        self._restart.set()

    # ---- внутренности ----
    def _set_status(self, connected: bool, msg: str) -> None:
        if connected != self.connected or msg:
            self.connected = connected
            if self.on_status:
                try:
                    self.on_status(connected, msg)
                except Exception:
                    pass

    def _open(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.settimeout(0.25)
            self._sock = s
            return True
        except OSError as e:
            s.close()                      # не оставляем незакрытый сокет при занятом порте
            self._sock = None
            self._set_status(False, f"port_error:{e}")
            return False

    def run(self) -> None:
        last_rx = 0.0
        while not self._stop_evt.is_set():
            self._restart.clear()
            if self._sock is None and not self._open():
                self._stop_evt.wait(2.0)       # порт занят — повторим позже
                continue
            self._set_status(False, "")
            while not self._restart.is_set():
                try:
                    data, _addr = self._sock.recvfrom(1024)
                except socket.timeout:
                    if self.connected and time.monotonic() - last_rx > self.timeout:
                        self._set_status(False, "timeout")
                    continue
                except OSError:
                    break                      # сокет умер — пересоздаём
                t = parse_packet(data)
                if t is None:
                    continue                   # битый пакет игнорируем
                # Счётчик потерь по необязательному ID (если он есть).
                if len(data) >= PACKET_SIZE + 4:
                    pid = struct.unpack("<i", data[PACKET_SIZE:PACKET_SIZE + 4])[0]
                    if self._last_id is not None and 0 < pid - self._last_id < 1000:
                        self.lost_packets += pid - self._last_id - 1
                    self._last_id = pid
                last_rx = time.monotonic()
                self.last = t
                if not self.connected:
                    self._set_status(True, "connected")
                if self.on_data:
                    try:
                        self.on_data(t)
                    except Exception:
                        pass
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        if self._sock:
            self._sock.close()
