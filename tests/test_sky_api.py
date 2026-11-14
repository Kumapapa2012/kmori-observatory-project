#!/usr/bin/env python3
"""天体の検索と導入の API を、サーバーを起動せずに呼んで確かめる。架台には接続しない。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from fastapi.responses import JSONResponse

from observatory.app import create_app
from observatory.config import load


class SkyApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = load("config/observatory.toml")
        cfg["server"]["state_file"] = str(Path(cls.tmp.name) / "state.json")
        cfg["capture"]["root"] = cls.tmp.name
        cfg["capture"]["preview_dir"] = cls.tmp.name
        cfg["mount"]["port"] = "/dev/null-not-a-mount"  # lifespan を動かさないので接続はしない
        cls.app = create_app(cfg)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def endpoint(self, path, method):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
                return route.endpoint
        raise KeyError(path)

    def test_lookup_returns_json_values(self):
        lookup = self.endpoint("/api/sky/lookup", "GET")
        for query in ("m1", "Uranus", "5h34m31.94s +22°00'52.2\"", "Pleiades"):
            with self.subTest(query=query):
                result = lookup(query)
                self.assertNotIsInstance(result, JSONResponse)
                json.dumps(result)  # numpy の値が残っていると失敗する
                self.assertTrue(0 <= result["az"] < 360)
                self.assertIn("radec", result)

    def test_lookup_reports_bad_input(self):
        result = self.endpoint("/api/sky/lookup", "GET")("not a star")
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 400)

    def test_catalog(self):
        catalog = self.endpoint("/api/sky/catalog", "GET")()
        keys = [t["key"] for t in catalog["quick"]]
        self.assertIn("m1", keys)
        self.assertIn("uranus", keys)
        json.dumps(catalog)

    def test_goto_and_tracking_need_the_mount(self):
        self.assertEqual(self.endpoint("/api/goto/plan", "POST")({"target": "m1"}).status_code, 503)
        self.assertEqual(self.endpoint("/api/tracking", "POST")({"target": "m1"}).status_code, 503)


if __name__ == "__main__":
    unittest.main()
