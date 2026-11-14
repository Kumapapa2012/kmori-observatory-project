#!/usr/bin/env python3
"""状態の保存と復元を確かめる。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.state import StateStore


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "var" / "state.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_defaults_without_file(self):
        self.assertEqual(StateStore(self.path).get()["recording"], {"kind": "none"})

    def test_survives_restart(self):
        StateStore(self.path).update(recording={"kind": "video"})
        self.assertEqual(StateStore(self.path).get()["recording"], {"kind": "video"})

    def test_broken_file_falls_back_to_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertIsNone(StateStore(self.path).get()["alignment"])

    def test_finder_defaults_to_center_for_old_files(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"alignment": null}', encoding="utf-8")
        self.assertEqual(StateStore(self.path).get()["finder"], {"x": 0.5, "y": 0.5})

    def test_get_returns_a_copy(self):
        store = StateStore(self.path)
        store.get()["recording"]["kind"] = "video"
        self.assertEqual(store.get()["recording"]["kind"], "none")


if __name__ == "__main__":
    unittest.main()
