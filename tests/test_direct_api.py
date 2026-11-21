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

    def place_near(self, target, d_az, d_alt):
        """目標の計算上の軸の角度から (d_az, d_alt) 度ずらした所に、疑似の基板を置く。"""
        sky = self.find_sky()
        az, alt = sky.altaz(target)
        self.fake.axes["1"].pos = (float(az) + d_az) * K
        self.fake.axes["2"].pos = (float(alt) + d_alt) * K
        time.sleep(0.3)
        return sky

    def find_sky(self):
        from observatory.sky import Sky
        for cell in self.endpoint("/api/tracking", "POST").__closure__:
            if isinstance(cell.cell_contents, Sky):
                return cell.cell_contents
        raise AssertionError("sky not found")

    def test_tracking_refuses_far_target(self):
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        self.place_near("polaris", 0.0, -20.0)
        code, body = self.call("/api/tracking", "POST", {"target": "polaris"})
        self.assertEqual(code, 409, body)
        self.assertIn("先に導入", body["error"])

    def test_tracking_holds_start_offset(self):
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        sky = self.place_near("polaris", 1.0, 0.5)
        code, body = self.call("/api/tracking", "POST", {"target": "polaris"})
        self.assertEqual(code, 200, body)
        self.addCleanup(lambda: self.call("/api/tracking", "DELETE"))
        base = sky.rates("polaris")[0]
        sign = 1.0 if base >= 0 else -1.0
        # 方位が追尾の向きと逆へ 0.3° 遅れた。開始時の差（+1.0°）へ戻すよう、追尾を速める
        self.fake.axes["1"].pos -= sign * 0.3 * K
        time.sleep(0.3)
        self.supervisor.on_tick(self.mount)
        rate = self.mount.status()["tracking"]["az"]
        self.assertGreater(abs(rate), abs(base) + 40.0)
        self.assertEqual(rate >= 0, sign > 0)

    def test_stick_moves_update_tracking_hold(self):
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        self.place_near("polaris", 1.0, 0.5)
        code, body = self.call("/api/tracking", "POST", {"target": "polaris"})
        self.assertEqual(code, 200, body)
        self.addCleanup(lambda: self.call("/api/tracking", "DELETE"))
        tracking = self.find_tracking()
        self.assertAlmostEqual(tracking["hold"]["alt"], 0.5, delta=0.05)
        # 十字キーで高度を上げて離すと、新しい向きを保つ（引き戻さない）
        self.mount.move("alt", 1, 5)
        time.sleep(0.6)
        self.supervisor.on_tick(self.mount)
        self.mount.drive(0, 0)
        time.sleep(0.3)
        self.supervisor.on_tick(self.mount)
        self.assertGreater(tracking["hold"]["alt"], 0.55)
        self.assertIsNotNone(tracking["target"])
        self.assertIn("alt", self.mount.status()["tracking"])

    def find_tracking(self):
        for cell in self.endpoint("/api/tracking", "POST").__closure__:
            v = cell.cell_contents
            if isinstance(v, dict) and "hold" in v and "follow" in v:
                return v
        raise AssertionError("tracking not found")

    def test_sky_mask_round_trip(self):
        _, mask = self.call("/api/sky-mask", "GET")
        self.assertEqual(len(mask["bins"]), 36)
        bins = [i < 18 for i in range(36)]
        code, saved = self.call("/api/sky-mask", "POST", {"bins": bins, "min_alt": 25})
        self.assertEqual(code, 200, saved)
        _, mask = self.call("/api/sky-mask", "GET")
        self.assertEqual(mask, {"bins": bins, "min_alt": 25.0})
        code, body = self.call("/api/sky-mask", "POST", {"bins": [False] * 36})
        self.assertEqual(code, 400)

    def test_plate_alignment_model_drives_goto_plan(self):
        # プレートソルブで傾きまで求めた記録があれば、導入の計画もそのモデルで軸の角度を出す
        from observatory import alignment as A
        params = {"az_offset": -7.8, "alt_offset": -2.0, "tilt_x": 0.5, "tilt_y": -0.3}
        from observatory.safety import Reference
        self.call("/api/reference", "POST", _Req(), {"kind": "power_on"})
        store = self.find_store()
        store.update(alignment={**params, "star": "plate", "source": "plate", "label": "プレートソルブ（3 点）",
                                "time": time.time(), "clock_offset": 0.0, "errors": [0.01]})
        self.mount.set_reference(Reference(kind="plate", label="プレートソルブ", **params))
        code, plan = self.call("/api/goto/plan", "POST", {"target": "polaris"})
        self.assertEqual(code, 200, plan)
        sky = self.find_sky()
        az, alt = sky.altaz("polaris")
        want = A.axis_of(params, float(az), float(alt), 0.0)
        self.assertAlmostEqual(plan["plan"]["axis_target"]["az"], want["az"], delta=0.01)
        self.assertAlmostEqual(plan["plan"]["axis_target"]["alt"], want["alt"], delta=0.01)

    def find_store(self):
        from observatory.state import StateStore
        for cell in self.endpoint("/api/sky-mask", "GET").__closure__:
            if isinstance(cell.cell_contents, StateStore):
                return cell.cell_contents
        raise AssertionError("store not found")

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
