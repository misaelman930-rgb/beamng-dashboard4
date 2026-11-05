"""Тесты подстройки шкал под машину: python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.car_profile import SPEED_CAP, learn, scale_for   # noqa: E402


class CarProfileTests(unittest.TestCase):
    def test_starts_at_200_and_grows_to_cap_320(self):
        p = {}
        self.assertEqual(scale_for(p, "bmw")["max_kmh"], 200.0)
        learn(p, "bmw", 250, 3000)
        self.assertEqual(p["bmw"]["max_kmh"], 280.0)        # 250*1.1 → 275 → округление до 20
        learn(p, "bmw", 400, 3000)                           # выбросы не дают выйти за потолок
        self.assertEqual(p["bmw"]["max_kmh"], SPEED_CAP)
        self.assertEqual(scale_for(p, "bmw")["max_kmh"], 320.0)

    def test_rpm_learned_per_car(self):
        p = {}
        self.assertTrue(learn(p, "ETK", 50, 8200))
        self.assertGreaterEqual(p["ETK"]["max_rpm"], 8200)
        self.assertEqual(scale_for(p, "ETK")["max_rpm"] % 500, 0)
        self.assertEqual(scale_for(p, "OTHER")["max_rpm"], 7000.0)   # другая машина не затронута

    def test_no_change_returns_false(self):
        p = {}
        learn(p, "x", 100, 3000)
        self.assertFalse(learn(p, "x", 60, 2000))

    def test_empty_name_uses_default_key(self):
        p = {}
        learn(p, "", 150, 3000)
        self.assertIn("default", p)


if __name__ == "__main__":
    unittest.main()
