"""Тесты установки на телефон (PWA): манифест, иконки, раздача файлов."""
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.dashboard_server import STATIC_DIR, _Handler, STATIC_FILES   # noqa: E402


class PwaTests(unittest.TestCase):
    def setUp(self):
        handler = type("H", (_Handler,), {"controller": None})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()

    def test_manifest_served_and_valid(self):
        with urlopen(self.base + "/manifest.webmanifest", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("manifest", r.headers["Content-Type"])
            m = json.loads(r.read())
        self.assertEqual(m["start_url"], "/digital")
        self.assertEqual(m["display"], "fullscreen")
        self.assertTrue(any(i["sizes"] == "192x192" for i in m["icons"]))

    def test_icons_are_png(self):
        for path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
            with urlopen(self.base + path, timeout=5) as r:
                self.assertEqual(r.read(8), b"\x89PNG\r\n\x1a\n", path)

    def test_unknown_static_is_404(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as cm:
            urlopen(self.base + "/../server.py", timeout=5)
        self.assertIn(cm.exception.code, (404, 400))

    def test_digital_page_links_manifest(self):
        with urlopen(self.base + "/digital", timeout=5) as r:
            body = r.read().decode("utf-8")
        self.assertIn('rel="manifest"', body)


if __name__ == "__main__":
    unittest.main()
