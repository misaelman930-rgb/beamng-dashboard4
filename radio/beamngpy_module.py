"""
Необязательный модуль: телеметрия через BeamNGpy (вместо OutGauge).

ЧЕМ ОТЛИЧАЕТСЯ ОТ OutGauge
--------------------------
* OutGauge — это простая «трансляция» из обычной BeamNG.drive: включил в
  настройках и получаешь UDP-пакеты. Ничего не нужно устанавливать, но набор
  данных фиксирован (скорость, обороты, передача, лампы, педали).
* BeamNGpy — Python-API для ИССЛЕДОВАНИЙ и симуляции. Он управляет игрой
  (запускает сценарии, ставит машины, читает любые датчики: электрика,
  IMU, GPS, повреждения, положение в пространстве).

ОГРАНИЧЕНИЯ BeamNGpy
--------------------
* Официально рассчитан на BeamNG.tech — исследовательскую версию с лицензией
  (бесплатна для академического использования, платная для коммерческого).
  Обычная BeamNG.drive с BeamNGpy «в основном» не поддерживается: часть
  функций работает, часть — нет, и совместимость версий строгая
  (версия beamngpy должна соответствовать версии игры).
* Нужно запускать игру из скрипта (или подключаться к уже запущенной с
  открытым портом) и держать открытым TCP-порт (по умолчанию 25252).
* Опрос датчиков тяжелее по нагрузке, чем пассивный приём UDP.

Поэтому основной путь приложения — OutGauge, а этот модуль — запасной вариант
для тех, у кого есть BeamNG.tech. Он выдаёт тот же класс Telemetry, так что
правила и аудио работают без изменений.

ИСПОЛЬЗОВАНИЕ
-------------
    pip install beamngpy
    from radio.beamngpy_module import BeamNGPyListener
    lst = BeamNGPyListener(host="localhost", port=25252)
    lst.start()          # дальше читайте lst.last, как у TelemetryListener
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .telemetry import (DL_ABS, DL_FULLBEAM, DL_HANDBRAKE, DL_SIGNAL_L, DL_SIGNAL_R, Telemetry)


class BeamNGPyListener(threading.Thread):
    """Подключается к уже запущенной BeamNG.tech и опрашивает датчик Electrics."""

    def __init__(self, host: str = "localhost", port: int = 25252, hz: float = 20.0,
                 on_status: Optional[Callable[[bool, str], None]] = None):
        super().__init__(daemon=True, name="BeamNGpyListener")
        self.host, self.port, self.period = host, port, 1.0 / hz
        self.on_status = on_status
        self.connected = False
        self.last: Optional[Telemetry] = None
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def _status(self, ok: bool, msg: str) -> None:
        self.connected = ok
        if self.on_status:
            self.on_status(ok, msg)

    def run(self) -> None:
        try:
            from beamngpy import BeamNGpy                    # type: ignore
            from beamngpy.sensors import Electrics            # type: ignore
        except ImportError:
            self._status(False, "beamngpy not installed")
            return
        while not self._stop_evt.is_set():                       # внешний цикл = автопереподключение
            bng = None
            try:
                bng = BeamNGpy(self.host, self.port)
                bng.open(launch=False)                        # подключиться к запущенной игре
                vehicles = bng.get_current_vehicles()
                if not vehicles:
                    raise RuntimeError("no vehicles in scenario")
                veh = next(iter(vehicles.values()))
                veh.connect(bng)
                el = Electrics()
                veh.attach_sensor("electrics", el)
                self._status(True, "connected")
                while not self._stop_evt.is_set():
                    veh.sensors.poll()
                    d = veh.sensors["electrics"]
                    self.last = self._convert(d)
                    time.sleep(self.period)
            except Exception as e:                            # noqa: BLE001 — игра закрыта и т.п.
                self._status(False, str(e))
                self.last = None
            finally:
                try:
                    if bng:
                        bng.close()
                except Exception:                              # noqa: BLE001
                    pass
            self._stop_evt.wait(3.0)

    @staticmethod
    def _convert(d: dict) -> Telemetry:
        """Электрика BeamNG → наш Telemetry (имена полей — из таблицы electrics)."""
        lights = 0
        if d.get("parkingbrake", 0) > 0.5:
            lights |= DL_HANDBRAKE
        if d.get("highbeam"):
            lights |= DL_FULLBEAM
        if d.get("abs_active") or d.get("abs"):
            lights |= DL_ABS
        sig = d.get("signal_L", 0), d.get("signal_R", 0)
        if sig[0]:
            lights |= DL_SIGNAL_L
        if sig[1]:
            lights |= DL_SIGNAL_R
        gear_idx = d.get("gear_index", 0)                     # -1 = R, 0 = N, 1.. = передачи
        return Telemetry(
            car="bng", gear=int(gear_idx) + 1, speed_ms=float(d.get("wheelspeed", 0.0)),
            rpm=float(d.get("rpm", 0.0)), turbo=float(d.get("turboBoost", 0.0)),
            engine_temp=float(d.get("watertemp", 0.0)), fuel=float(d.get("fuel", 0.0)),
            oil_temp=float(d.get("oiltemp", 0.0)), show_lights=lights,
            dash_lights=0xFFFF, throttle=float(d.get("throttle", 0.0)),
            brake=float(d.get("brake", 0.0)), clutch=float(d.get("clutch", 0.0)))
