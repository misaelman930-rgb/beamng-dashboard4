"""
Тесты ядра (без Qt и VLC):  python -m unittest discover -s tests -v
"""
import os
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.rules import RuleEngine, default_rules, interp_curve          # noqa: E402
from radio.settings import DEFAULTS, Settings                              # noqa: E402
from radio.stations import StationStore                                    # noqa: E402
from radio.telemetry import (DL_ABS, DL_HANDBRAKE, DL_SIGNAL_L, PACKET_SIZE,  # noqa: E402
                             Telemetry, TelemetryListener, build_packet, parse_packet)
from tools.outgauge_emulator import state_at                               # noqa: E402


class TelemetryTests(unittest.TestCase):
    def test_roundtrip(self):
        t = Telemetry(car="bmw", gear=4, speed_ms=27.7, rpm=3500, fuel=0.5, engine_temp=90,
                      show_lights=DL_ABS | DL_SIGNAL_L, throttle=0.4, brake=0.1)
        p = parse_packet(build_packet(t, 7))
        self.assertEqual(len(build_packet(t)), PACKET_SIZE + 4)
        self.assertAlmostEqual(p.speed_kmh, 99.72, places=1)
        self.assertEqual(p.gear, 4)
        self.assertTrue(p.abs_active and p.signal_left and p.signal_any)
        self.assertFalse(p.handbrake)
        self.assertEqual(p.car, "bmw")

    def test_92_bytes_without_id(self):
        self.assertIsNotNone(parse_packet(build_packet(Telemetry(), with_id=False)))

    def test_garbage(self):
        self.assertIsNone(parse_packet(b"\x00" * 10))
        bad = bytearray(build_packet(Telemetry()))
        bad[12:16] = b"\xff\xff\xff\x7f"          # NaN в поле Speed
        self.assertIsNone(parse_packet(bytes(bad)))

    def test_listener_loopback_and_reconnect(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        events = []
        lst = TelemetryListener(port=port, timeout=0.6, on_status=lambda ok, m: events.append(ok))
        lst.start()
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            time.sleep(0.4)
            for i in range(10):                          # «игра» запущена
                tx.sendto(build_packet(Telemetry(speed_ms=10), i), ("127.0.0.1", port))
                time.sleep(0.03)
            time.sleep(0.2)
            self.assertTrue(lst.connected)
            self.assertAlmostEqual(lst.last.speed_ms, 10, places=3)
            time.sleep(1.5)                              # «игра закрыта»
            self.assertFalse(lst.connected)
            tx.sendto(build_packet(Telemetry(speed_ms=5), 11), ("127.0.0.1", port))   # перезапуск
            time.sleep(0.4)
            self.assertTrue(lst.connected)
            tx.sendto(build_packet(Telemetry(), 20), ("127.0.0.1", port))             # пропуск ID 12..19
            time.sleep(0.3)
            self.assertGreaterEqual(lst.lost_packets, 8)
        finally:
            lst.stop(); tx.close()

    def test_port_busy_then_free(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        blocker.bind(("127.0.0.1", 0)); port = blocker.getsockname()[1]
        msgs = []
        lst = TelemetryListener(port=port, on_status=lambda ok, m: msgs.append(m))
        lst.start()
        time.sleep(0.5)
        lst.stop(); blocker.close()                       # главное — поток не падает и останавливается
        lst.join(3)
        self.assertFalse(lst.is_alive())

    def test_emulator_scenario(self):
        self.assertAlmostEqual(state_at(0, "drive").speed_kmh, 0)
        self.assertGreater(state_at(30, "drive").speed_kmh, 100)
        self.assertTrue(state_at(37, "drive").abs_active)
        self.assertTrue(state_at(45, "drive").handbrake)
        self.assertTrue(state_at(55, "drive").engine_off)


class RulesTests(unittest.TestCase):
    def test_curve(self):
        c = [[0, 0.4], [100, 0.8], [200, 1.0]]
        self.assertAlmostEqual(interp_curve(c, -5), 0.4)
        self.assertAlmostEqual(interp_curve(c, 50), 0.6)
        self.assertAlmostEqual(interp_curve(c, 150), 0.9)
        self.assertAlmostEqual(interp_curve(c, 999), 1.0)

    def test_while_duck_and_release(self):
        r = RuleEngine([{"enabled": True, "var": "signal_any", "op": ">", "value": 0.5, "for_s": 0,
                         "action": "duck", "param": 0.4, "mode": "while"}])
        self.assertEqual(r.evaluate({"signal_any": 1.0}, 0).duck, 0.4)
        self.assertEqual(r.evaluate({"signal_any": 0.0}, 1).duck, 1.0)

    def test_for_seconds(self):
        r = RuleEngine([{"enabled": True, "var": "engine_off", "op": ">", "value": 0.5, "for_s": 10,
                         "action": "pause", "mode": "while"}])
        self.assertFalse(r.evaluate({"engine_off": 1.0}, 0).pause)
        self.assertFalse(r.evaluate({"engine_off": 1.0}, 9.9).pause)
        self.assertTrue(r.evaluate({"engine_off": 1.0}, 10.1).pause)
        self.assertFalse(r.evaluate({"engine_off": 0.0}, 11).pause)
        self.assertFalse(r.evaluate({"engine_off": 1.0}, 12).pause)     # таймер начался заново

    def test_once_with_cooldown(self):
        fired = []
        r = RuleEngine([{"enabled": True, "var": "tc", "op": ">", "value": 0.5, "for_s": 0,
                         "action": "jingle", "param": "", "mode": "once", "cooldown_s": 5}],
                       on_action=lambda a, p: fired.append(a))
        for now, tc in [(0, 1), (0.1, 1), (0.2, 0), (1, 1), (6, 0), (7, 1)]:
            r.evaluate({"tc": float(tc)}, now)
        self.assertEqual(fired, ["jingle", "jingle"])    # второй фронт в t=1 заблокирован cooldown'ом

    def test_disabled_and_no_telemetry(self):
        r = RuleEngine([{"enabled": False, "var": "abs", "op": ">", "value": 0, "action": "mute", "mode": "while"}])
        self.assertFalse(r.evaluate({"abs": 1.0}, 0).mute)
        r2 = RuleEngine(default_rules())
        fx = r2.evaluate(None, 0)
        self.assertEqual((fx.duck, fx.pause, fx.mute), (1.0, False, False))

    def test_default_rules_with_telemetry(self):
        r = RuleEngine(default_rules())
        t = Telemetry(show_lights=DL_HANDBRAKE, rpm=900, speed_ms=0)
        self.assertFalse(r.evaluate(t.variables(), 0).pause)
        self.assertTrue(r.evaluate(t.variables(), 31).pause)             # ручник > 30 с


class SettingsStationsTests(unittest.TestCase):
    def test_settings_merge_and_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"volume": 33, "car_filter": {"strength": 0.9}}')
            s = Settings(__import__("pathlib").Path(p))
            self.assertEqual(s["volume"], 33)
            self.assertEqual(s["car_filter"]["strength"], 0.9)
            self.assertIn("rpm_max", s["car_filter"])        # недостающие ключи добавлены
            s["volume"] = 50; s.save()
            self.assertEqual(Settings(__import__("pathlib").Path(p))["volume"], 50)

    def test_broken_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{not json")
            s = Settings(__import__("pathlib").Path(p))
            self.assertEqual(s["udp_port"], DEFAULTS["udp_port"])

    def test_station_store(self):
        with tempfile.TemporaryDirectory() as d:
            path = __import__("pathlib").Path(d) / "st.json"
            st = StationStore(path)
            genres = {s.genre for s in st.stations}
            for g in ("rock", "electronic", "phonk", "retro", "jazz", "news"):
                self.assertIn(g, genres)
            mine = st.add("Test", "http://example.com/stream", "rock")
            st.toggle_favorite(mine.id)
            st2 = StationStore(path)
            self.assertTrue(st2.get(mine.id).favorite)
            self.assertTrue(st2.remove(mine.id))
            self.assertIsNone(StationStore(path).get(mine.id))
            self.assertTrue(st.by_genre("phonk"))

    def test_chanson_russian_and_own_radio(self):
        with tempfile.TemporaryDirectory() as d:
            st = StationStore(__import__("pathlib").Path(d) / "st.json")
            self.assertTrue(st.by_genre("chanson"))
            self.assertTrue(st.by_genre("russian"))
            trassa = st.get("trassa-fm")
            self.assertTrue(trassa.playable)
            self.assertEqual(len(trassa.rotate), 5)
            for sid in trassa.rotate:
                self.assertIsNotNone(st.get(sid), sid)   # все станции ротации существуют


if __name__ == "__main__":
    unittest.main()
