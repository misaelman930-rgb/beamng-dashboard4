"""Тесты сервера станций и клиента: python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from radio.remote import fetch_stations, normalize_server_url        # noqa: E402
from radio.stations import StationStore                             # noqa: E402
from server.app import make_server, validate_station                # noqa: E402

TOKEN = "s3cret-token"


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = make_server("127.0.0.1", 0, Path(cls.tmp.name) / "st.json", TOKEN)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def call(self, method, path, body=None, token=TOKEN):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_page_and_health(self):
        with urlopen(self.base + "/", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"BeamNG Radio", r.read())
        self.assertEqual(self.call("GET", "/healthz")[0], 200)

    def test_add_list_delete(self):
        code, st = self.call("POST", "/api/stations",
                             {"name": "Phonk FM", "url": "https://radio.example.com/phonk.mp3", "genre": "phonk"})
        self.assertEqual(code, 201)
        code, data = self.call("GET", "/api/stations")
        self.assertIn(st["id"], [s["id"] for s in data["stations"]])
        self.assertEqual(self.call("DELETE", "/api/stations/" + st["id"])[0], 200)
        self.assertEqual(self.call("DELETE", "/api/stations/" + st["id"])[0], 404)

    def test_write_requires_token(self):
        body = {"name": "x", "url": "https://a.example.com/s"}
        self.assertEqual(self.call("POST", "/api/stations", body, token=None)[0], 401)
        self.assertEqual(self.call("POST", "/api/stations", body, token="wrong")[0], 401)

    def test_bad_input_rejected(self):
        self.assertEqual(self.call("POST", "/api/stations", {"name": "x", "url": "javascript:alert(1)"})[0], 400)
        self.assertEqual(self.call("POST", "/api/stations", {"name": "x", "url": "http://a b"})[0], 400)
        self.assertEqual(self.call("POST", "/api/stations", {"name": "x", "url": "http://a.com:99999/x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/stations", ["not", "dict"])[0], 400)

    def test_writes_disabled_without_token(self):
        tmp = tempfile.TemporaryDirectory()
        srv = make_server("127.0.0.1", 0, Path(tmp.name) / "s.json", "")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = Request(f"http://127.0.0.1:{srv.server_address[1]}/api/stations",
                          data=b'{"url":"https://a.com/s"}', method="POST",
                          headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
            with self.assertRaises(HTTPError) as cm:
                urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 503)
        finally:
            srv.shutdown(); srv.server_close(); tmp.cleanup()

    def test_unknown_route(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)

    def test_client_fetch_end_to_end(self):
        self.call("POST", "/api/stations", {"name": "Jazz One", "url": "https://j.example.com/jazz", "genre": "jazz"})
        items = fetch_stations(self.base)
        self.assertTrue(any(i["name"] == "Jazz One" and i["genre"] == "jazz" for i in items))


class ValidationTests(unittest.TestCase):
    def test_validate(self):
        st, err = validate_station({"url": " https://x.example.com/a.mp3 ", "genre": "PHONK", "name": ""})
        self.assertEqual(err, "")
        self.assertEqual(st["genre"], "phonk")
        self.assertEqual(st["name"], "x.example.com")
        self.assertEqual(validate_station({"url": "ftp://x"})[1], "bad_url")
        self.assertEqual(validate_station({"url": "https://x.example.com", "genre": "weird"})[0]["genre"], "other")

    def test_normalize_server_url(self):
        self.assertEqual(normalize_server_url(" https://a.onrender.com/ "), "https://a.onrender.com")
        self.assertEqual(normalize_server_url(""), "")
        with self.assertRaises(ValueError):
            normalize_server_url("a.onrender.com")


class MergeTests(unittest.TestCase):
    def test_merge_add_update_remove(self):
        with tempfile.TemporaryDirectory() as d:
            store = StationStore(Path(d) / "st.json")
            n1 = store.merge_remote([{"id": "a1", "name": "A", "url": "https://a/1", "genre": "rock"},
                                     {"id": "b2", "name": "B", "url": "https://b/2", "genre": "jazz"}])
            self.assertEqual(n1, 2)
            self.assertEqual(store.merge_remote([{"id": "a1", "name": "A2", "url": "https://a/1", "genre": "rock"},
                                                 {"id": "b2", "name": "B", "url": "https://b/2", "genre": "jazz"}]), 1)
            self.assertEqual(store.get("r-a1").name, "A2")
            self.assertEqual(store.merge_remote([{"id": "b2", "name": "B", "url": "https://b/2", "genre": "jazz"}]), 1)
            self.assertIsNone(store.get("r-a1"))
            # удалить станцию сервера локально нельзя
            self.assertFalse(store.remove("r-b2"))
            # сохраняется между запусками
            self.assertTrue(StationStore(Path(d) / "st.json").get("r-b2").remote)


if __name__ == "__main__":
    unittest.main()
