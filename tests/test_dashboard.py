"""Тесты веб-панели: маршруты и JSON состояния. python -m unittest discover -s tests -v"""
import os
import sys
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.dashboard_server import DIGITAL_HTML, DASHBOARD_HTML, _Handler   # noqa: E402
from radio.stations import Station                                           # noqa: E402
from radio.telemetry import DL_SIGNAL_L, Telemetry                           # noqa: E402


def fake_controller(connected=True):
    tel = Telemetry(gear=3, speed_ms=30, rpm=4200, fuel=0.5, engine_temp=91, show_lights=DL_SIGNAL_L)
    return types.SimpleNamespace(
        connected=connected, last_telemetry=tel if connected else None,
        store=types.SimpleNamespace(stations=[Station(id="a", name="Test FM", url="https://x.example/s")]),
        current=None, audio=None, settings={"volume": 60, "muted": False},
        car_profiles={}, now_track="Test Track")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = fake_controller()
        handler = type("H", (_Handler,), {"controller": self.ctrl})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as r:
            return r.status, r.read().decode("utf-8")

    def test_pages_served(self):
        self.assertEqual(self.get("/")[0], 200)
        code, body = self.get("/digital")
        self.assertEqual(code, 200)
        self.assertIn('id="speed"', body)
        self.assertNotIn("не найден", body)          # страница действительно загрузилась из static/

    def test_state_has_speed(self):
        import json
        code, body = self.get("/api/state")
        d = json.loads(body)
        self.assertTrue(d["connected"])
        self.assertAlmostEqual(d["telemetry"]["speed_kmh"], 108.0, places=3)
        self.assertTrue(d["telemetry"]["signal_left"])
        self.assertEqual(d["track"], "Test Track")
        self.assertIn("max_kmh", d["scale"])
        self.assertIn("battery", d["telemetry"])

    def test_pages_not_empty(self):
        self.assertIn("speed", DIGITAL_HTML)
        self.assertNotIn("не найден", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
