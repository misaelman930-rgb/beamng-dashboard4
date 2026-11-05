"""
Эмулятор BeamNG.drive: шлёт фейковые пакеты OutGauge по UDP, чтобы проверять
радио без запуска игры.

Примеры:
    python tools/outgauge_emulator.py                    # демо-сценарий «поездка»
    python tools/outgauge_emulator.py --port 4444 --hz 30
    python tools/outgauge_emulator.py --scenario highway # только трасса
    python tools/outgauge_emulator.py --interactive      # ручное управление из консоли

Сценарий «drive» (цикл ~60 с): стоим → разгон → поворотник → трасса → ABS при
торможении → остановка с ручником → заглушили мотор → снова завели.
"""
from __future__ import annotations

import argparse
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.telemetry import (DL_ABS, DL_FULLBEAM, DL_HANDBRAKE, DL_SIGNAL_L,  # noqa: E402
                             DL_SIGNAL_R, DL_TC, Telemetry, build_packet)

GEAR_SPEEDS = [0, 20, 45, 75, 110, 150, 200]   # км/ч: верхняя граница передач 1..6


def lerp(a, b, k):
    return a + (b - a) * max(0.0, min(1.0, k))


def state_at(t: float, scenario: str) -> Telemetry:
    """Возвращает состояние машины в момент времени t (сек) выбранного сценария."""
    c = t % 60.0 if scenario == "drive" else t
    speed = 0.0
    lights = 0
    thr = brk = 0.0
    engine_on = True

    if scenario == "highway":
        speed = 125 + 15 * math.sin(t / 4)
        thr = 0.35
    elif scenario == "city":
        speed = 25 + 20 * abs(math.sin(t / 6))
        lights |= DL_SIGNAL_L if int(t * 2) % 2 == 0 and int(t / 10) % 2 == 0 else 0
        thr = 0.25
    else:  # drive
        if c < 5:                                   # стоим, мотор работает
            speed = 0
        elif c < 15:                                # разгон до 70
            speed = lerp(0, 70, (c - 5) / 10); thr = 0.8
        elif c < 20:                                # правый поворотник
            speed = 70
            lights |= DL_SIGNAL_R if int(c * 2) % 2 == 0 else 0
        elif c < 32:                                # разгон до 150 (трасса), TC на старте
            speed = lerp(70, 150, (c - 20) / 12); thr = 1.0
            if c < 22:
                lights |= DL_TC
            lights |= DL_FULLBEAM
        elif c < 40:                                # торможение с ABS
            speed = lerp(150, 0, (c - 32) / 8); brk = 0.9
            lights |= DL_ABS if speed > 15 else 0
        elif c < 52:                                # стоим на ручнике
            speed = 0
            lights |= DL_HANDBRAKE
        elif c < 58:                                # мотор заглушен
            speed = 0
            lights |= DL_HANDBRAKE
            engine_on = False
        else:                                       # завели снова
            speed = 0

    # передача по скорости, обороты по передаче
    gear = 1
    for i, top in enumerate(GEAR_SPEEDS[1:], start=1):
        if speed <= top:
            gear = i + 1
            break
    else:
        gear = len(GEAR_SPEEDS) + 1
    if speed < 0.5:
        gear = 1                                    # нейтраль
    lo = GEAR_SPEEDS[max(0, gear - 2)]
    hi = GEAR_SPEEDS[min(len(GEAR_SPEEDS) - 1, gear - 1)] or 20
    rpm = 900 + 5600 * max(0.0, min(1.0, (speed - lo) / max(1, hi - lo))) if gear > 1 else 900 + 2500 * thr
    if not engine_on:
        rpm = 0.0
    return Telemetry(car="demo", gear=gear, speed_ms=speed / 3.6, rpm=rpm, turbo=0.4 * thr,
                     engine_temp=88 + 4 * thr, fuel=max(0.05, 0.8 - (t % 600) / 1000),
                     oil_pressure=3.0, oil_temp=95, dash_lights=0xFFFF, show_lights=lights,
                     throttle=thr, brake=brk, clutch=0.0)


def interactive(sock, addr, hz):
    """Ручной режим: команды в консоли меняют скорость и лампы (работает и на Windows)."""
    import queue
    import threading
    print("Команды: s<км/ч> (скорость), r<об/мин>, l (левый), p (правый), a (ABS), t (TC), h (ручник), "
          "e (мотор вкл/выкл), q (выход)")
    q: "queue.Queue[str]" = queue.Queue()

    def reader():                                   # stdin читаем в отдельном потоке
        for line in sys.stdin:
            q.put(line.strip())
        q.put("q")

    threading.Thread(target=reader, daemon=True).start()
    spd, rpm, lights, pid, engine = 0.0, 900.0, 0, 0, True
    flags = {"l": DL_SIGNAL_L, "p": DL_SIGNAL_R, "a": DL_ABS, "t": DL_TC, "h": DL_HANDBRAKE}
    while True:
        while not q.empty():
            cmd = q.get()
            try:
                if cmd == "q":
                    return
                if cmd == "e":
                    engine = not engine
                elif cmd[:1] == "s":
                    spd = float(cmd[1:] or 0)
                elif cmd[:1] == "r":
                    rpm = float(cmd[1:] or 0)
                elif cmd in flags:
                    lights ^= flags[cmd]
            except ValueError:
                print("Неверная команда:", cmd)
        t = Telemetry(car="demo", gear=2 if spd > 1 else 1, speed_ms=spd / 3.6,
                      rpm=rpm if engine else 0, fuel=0.6, engine_temp=90, show_lights=lights,
                      dash_lights=0xFFFF)
        sock.sendto(build_packet(t, pid), addr)
        pid += 1
        time.sleep(1.0 / hz)


def main() -> int:
    ap = argparse.ArgumentParser(description="OutGauge emulator for BeamNG Radio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4444)
    ap.add_argument("--hz", type=float, default=30.0, help="пакетов в секунду")
    ap.add_argument("--scenario", choices=["drive", "highway", "city"], default="drive")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--drop", type=float, default=0.0, help="доля теряемых пакетов 0..1 (тест потерь)")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (args.host, args.port)
    print(f"Отправляю OutGauge на {args.host}:{args.port} ({args.scenario}, {args.hz} Гц). Ctrl+C — стоп.")
    if args.interactive:
        interactive(sock, addr, args.hz)
        return 0
    import random
    t0 = time.monotonic()
    pid = 0
    try:
        while True:
            t = time.monotonic() - t0
            if random.random() >= args.drop:
                sock.sendto(build_packet(state_at(t, args.scenario), pid), addr)
            pid += 1
            time.sleep(1.0 / args.hz)
    except KeyboardInterrupt:
        print("\nСтоп.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
