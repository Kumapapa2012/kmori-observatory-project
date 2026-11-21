#!/usr/bin/env python3
"""直結版のサーバーの API（向きの基準、導入）を、疑似の基板をつないだ状態で確かめる。実機には接続しない。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.responses import JSONResponse

from fake_motor import CPR, FakeMotorBoard
from observatory.app import MountSupervisor, create_app
from observatory.config import load
from observatory.direct_mount import DirectMount
from observatory.motor import MotorBoard

K = CPR / 360.0


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class DirectApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = load("config/observatory.toml")
        cfg["server"]["state_file"] = str(Path(self.tmp.name) / "state.json")
        cfg["capture"]["root"] = self.tmp.name
        cfg["capture"]["preview_dir"] = self.tmp.name
        cfg["mount"]["backend"] = "direct"
        cfg["site"].update(latitude=35.7333, longitude=139.7538)
        self.app = create_app(cfg)
        self.supervisor = self.find_supervisor()
        self.fake = FakeMotorBoard(initialized=False)
        self.mount = DirectMount("fake", cfg["mount"]["direct"], board=MotorBoard("fake", link=self.fake),
                                 poll_interval=0.05)
        self.addCleanup(self.mount.close)
        self.supervisor.mount = self.mount
        self.supervisor.on_connect(self.mount)

    def endpoint(self, path, method):
        for route in self.app.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
                return route.endpoint
        raise KeyError(path)

    def find_supervisor(self):
        for cell in self.endpoint("/api/reference", "GET").__closure__:
            if isinstance(cell.cell_contents, MountSupervisor):
                return cell.cell_contents
        raise AssertionError("supervisor not found")

    def call(self, path, method, *args):
        result = self.endpoint(path, method)(*args)
        if isinstance(result, JSONResponse):
            import json
            return result.status_code, json.loads(result.body)
        return 200, result

    def test_reference_options_and_power_on(self):
        _, ref = self.call("/api/reference", "GET")
        self.assertFalse(ref["referenced"])
        self.assertFalse(ref["restricted"])
        kinds = [(o["kind"], o.get("key")) for o in ref["options"]]
        self.assertIn(("power_on", None), kinds)
        self.assertIn(("landmark", "skytree"), kinds)
        code, _ = self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        self.assertEqual(code, 200)
        self.assertTrue(self.mount.status()["referenced"])
        self.assertEqual(self.mount.reference.kind, "power_on")

    def test_landmark_sets_offsets(self):
        self.fake.axes["1"].pos = -10.0 * K
        self.fake.axes["2"].pos = 2.0 * K
        time.sleep(0.2)
        code, result = self.call("/api/reference", "POST", _Req(), {"kind": "landmark", "key": "skytree"})
        self.assertEqual(code, 200)
        self.assertAlmostEqual(result["az_offset"], 126.49, delta=0.01)
        self.assertAlmostEqual(result["alt_offset"], 3.72, delta=0.01)
        self.assertEqual(self.mount.reference.kind, "landmark")

    def test_goto_needs_reference_then_moves(self):
        code, body = self.call("/api/goto/plan", "POST", {"target": "polaris"})
        self.assertEqual(code, 409)
        self.assertIn("基準", body["error"])
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        code, plan = self.call("/api/goto/plan", "POST", {"target": "polaris"})
        self.assertEqual(code, 200, plan)
        target = plan["plan"]["axis_target"]
        code, body = self.call("/api/goto", "POST", _Req(), {"plan_id": plan["plan_id"]})
        self.assertEqual(code, 200, body)
        self.assertTrue(wait_for(lambda: self.mount.status()["goto"] is None, timeout=60))
        self.assertTrue(self.mount.status()["goto_result"]["ok"])
        self.assertAlmostEqual(self.mount.status()["raw"]["alt"], target["alt"], delta=0.02)

    def test_power_glitch_clears_reference(self):
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        time.sleep(0.2)
        self.fake.power_glitch()
        self.assertTrue(wait_for(lambda: not self.mount.status()["referenced"]))
        self.supervisor.on_tick(self.mount)
        _, ref = self.call("/api/reference", "GET")
        self.assertFalse(ref["referenced"])
        self.assertIsNone(self.endpoint("/api/status", "GET")()["alignment"])


class _Req:
    client = None


if __name__ == "__main__":
    unittest.main()
