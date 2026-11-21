#!/usr/bin/env python3
"""プレートソルブのアラインメント（向きのモデルの推定と、点を選んで解く進行）を、架台と ASTAP を模して確かめる。"""
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory import alignment as A
from observatory import plate as P

TRUE = {"az_offset": -7.8, "alt_offset": -2.1, "tilt_x": 0.5, "tilt_y": -0.3}


class ModelTest(unittest.TestCase):
    def test_round_trip_with_tilt(self):
        for az, alt in [(10, 20), (95, 45), (200, 70), (330, 30)]:
            raw = A.axis_of(TRUE, az, alt)
            back = A.sky_of(TRUE, raw)
            self.assertAlmostEqual(A.wrap180(back["az"] - az), 0.0, places=9)
            self.assertAlmostEqual(back["alt"], alt, places=9)

    def test_old_alignment_without_tilt(self):
        old = {"az_offset": 3.0, "alt_offset": -1.0}
        self.assertEqual(A.pointing(old, {"az": 10.0, "alt": 20.0}), {"az": 13.0, "alt": 19.0})

    def test_fit_three_points(self):
        samples = [(A.axis_of(TRUE, az, alt), {"az": az, "alt": alt}) for az, alt in [(70, 40), (160, 60), (250, 50)]]
        params, errors = A.fit(samples)
        for k, v in TRUE.items():
            self.assertAlmostEqual(params[k], v, places=3)
        self.assertLess(max(errors), 1e-3)

    def test_fit_one_point_offsets_only(self):
        params, errors = A.fit([({"az": 0.0, "alt": 40.0}, {"az": 8.0, "alt": 42.0})])
        self.assertAlmostEqual(params["az_offset"], 8.0, places=4)
        self.assertAlmostEqual(params["alt_offset"], 2.0, places=4)
        self.assertEqual(params["tilt_x"], 0.0)

    def test_axis_near(self):
        self.assertAlmostEqual(A.axis_of({"az_offset": 0.0}, 350.0, 30.0, near_az=0.0)["az"], -10.0)
        self.assertAlmostEqual(A.axis_of({"az_offset": 0.0}, 350.0, 30.0, near_az=300.0)["az"], 350.0)


class PixelTest(unittest.TestCase):
    # 2026-11-21 22:5x のファインダーの解（カストル付近、1920×1080）
    VALUES = {"CRPIX1": "960.5", "CRPIX2": "540.5", "CRVAL1": "118.91019113267350", "CRVAL2": "37.006919262252332",
              "CD1_1": "-4.0659432903319814E-003", "CD1_2": "-1.1664383654963636E-002",
              "CD2_1": "-1.1606231813377672E-002", "CD2_2": "3.9667765743446153E-003"}

    def test_center(self):
        ra, dec = P.pixel_to_radec(self.VALUES, 959.5, 539.5)
        self.assertAlmostEqual(ra, 118.9102, places=3)
        self.assertAlmostEqual(dec, 37.0069, places=3)

    def test_castor_position(self):
        # カストルは画像の (1464, 330)（左上原点）に写っていた
        ra, dec = P.pixel_to_radec(self.VALUES, 1464, 330)
        self.assertLess(A.separation(ra, dec, 113.65, 31.888), 0.02)

    def test_sky_mask(self):
        self.assertEqual(P.check_sky_mask({"bins": [True] * 36, "min_alt": 15})["min_alt"], 15.0)
        with self.assertRaises(ValueError):
            P.check_sky_mask({"bins": [False] * 36})
        with self.assertRaises(ValueError):
            P.check_sky_mask({"bins": [True] * 10})


class StackTest(unittest.TestCase):
    def test_picks_last_frame_of_each_exposure(self):
        import numpy as np
        rng = np.random.default_rng(1)
        frames = []
        for exposure in range(5):
            base = rng.integers(0, 200, (40, 40)).astype(np.uint8)
            for k in range(15):
                f = base.copy()
                f[0, 0] = k  # 圧縮による小さな差
                frames.append(f)
        picked = list(P.distinct_exposures(iter(frames)))
        # 最初の露出は使わず、2〜4 番目の露出の最後のコマ（5 番目は次の切り替わりが来ないので使わない）
        self.assertEqual(len(picked), 3)
        for got, exposure in zip(picked, (1, 2, 3)):
            self.assertIs(got, frames[exposure * 15 + 14])


class FakeRig:
    """本当の向きのモデル TRUE で動く架台。解くと本当の向きを (赤経, 赤緯) の代わりに (方位/15, 高度) で返す。"""

    def __init__(self, fail_az=None):
        self.raw = {"az": 0.0, "alt": 0.0}
        self.moves = []
        self.fail_az = fail_az or []
        self.commits = []

    def hooks(self):
        def move(step):
            for axis in ("az", "alt"):
                assert abs(step[axis] - self.raw[axis]) <= 40.0 + 1e-9, step
            self.moves.append(dict(step))
            self.raw = dict(step)

        def solve(path, hint, radius):
            sky = A.sky_of(TRUE, self.raw)
            if any(abs(A.wrap180(sky["az"] - f)) < 10 for f in self.fail_az):
                return None
            return {"ra_hours": sky["az"] / 15.0, "dec": sky["alt"], "scale": 44.4, "rotation": 0.0, "seconds": 0.1}

        return {
            "raw": lambda: dict(self.raw),
            "move": move,
            "stop": lambda: None,
            "capture": lambda path: True,
            "solve": solve,
            "altaz_of": lambda ra, dec, t: (ra * 15.0, dec),
            "radec_of": lambda az, alt: (az / 15.0, alt),
            "avoid": lambda az, alt: None,
            "commit": lambda params, points, errors: self.commits.append((params, points, errors)),
        }


def run(rig, mask, **kw):
    with tempfile.TemporaryDirectory() as tmp:
        job = P.PlateAlignment(rig.hooks(), {}, mask, workdir=tmp, settle=0.0, **kw)
        job.start()
        job.thread.join(timeout=30)
        return job.snapshot()


class PlateAlignmentTest(unittest.TestCase):
    def test_three_points_reach_tolerance(self):
        rig = FakeRig()
        status = run(rig, P.DEFAULT_SKY_MASK)
        self.assertEqual(status["state"], "done", status["message"])
        solved = [p for p in status["points"] if p["state"] == "solved"]
        self.assertEqual(len(solved), 3)
        # 方位で 90° 以上離れている
        azs = sorted(p["az"] for p in solved)
        gaps = [b - a for a, b in zip(azs, azs[1:])] + [360 - azs[-1] + azs[0]]
        self.assertGreaterEqual(min(gaps), 90.0)
        params = rig.commits[-1][0]
        for k, v in TRUE.items():
            self.assertAlmostEqual(params[k], v, places=2)

    def test_first_point_near_power_on_direction(self):
        rig = FakeRig()
        status = run(rig, P.DEFAULT_SKY_MASK)
        first = status["points"][0]
        self.assertLess(abs(A.wrap180(first["az"] - 0.0)), 10.0)
        self.assertGreaterEqual(first["alt"], 30.0)
        for p in status["points"]:
            self.assertLessEqual(p["alt"], 50.0)

    def test_replaces_unsolved_point(self):
        # 東半分だけ見える空で、方位 160° 付近は（雲で）解けない
        bins = [45 <= (i + 0.5) * 10 <= 225 for i in range(36)]
        rig = FakeRig(fail_az=[160.0])
        rig.raw = A.axis_of({}, 90.0, 0.0)
        status = run(rig, {"bins": bins, "min_alt": 20.0})
        failed = [p for p in status["points"] if p["state"] == "failed"]
        solved = [p for p in status["points"] if p["state"] == "solved"]
        self.assertTrue(failed)
        self.assertGreaterEqual(len(solved), 3)
        for p in solved:
            self.assertTrue(P.visible({"bins": bins}, p["az"]))
        self.assertIn(status["state"], ("done", "done_warn"))

    def test_none_solved_does_not_commit(self):
        rig = FakeRig(fail_az=[i * 20.0 for i in range(18)])
        status = run(rig, P.DEFAULT_SKY_MASK, max_attempts=3)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(rig.commits, [])

    def test_cancel(self):
        rig = FakeRig()
        hooks = rig.hooks()
        original = hooks["move"]

        def slow_move(step):
            time.sleep(0.2)
            original(step)
        hooks["move"] = slow_move
        with tempfile.TemporaryDirectory() as tmp:
            job = P.PlateAlignment(hooks, {}, P.DEFAULT_SKY_MASK, workdir=tmp, settle=0.0)
            job.start()
            time.sleep(0.05)
            job.cancel()
            job.thread.join(timeout=10)
            self.assertEqual(job.snapshot()["state"], "cancelled")
        self.assertEqual(rig.commits, [])


class SloppyRig(FakeRig):
    """止まる位置が毎回少しずれる架台（2026-11-22 実測で 0.2〜0.3°）。最初の導入でもずれている。"""

    def __init__(self, scatter=0.25, seed=3):
        super().__init__()
        import random
        self.rng = random.Random(seed)
        self.scatter = scatter

    def hooks(self):
        h = super().hooks()

        def move(step):
            self.moves.append(dict(step))
            self.raw = {a: step[a] + self.rng.uniform(-self.scatter, self.scatter) for a in ("az", "alt")}
        h["move"] = move
        return h


def center(rig, target, params, **kw):
    h = rig.hooks()
    tracks = []
    h.update({"wait_goto": lambda: None, "track": lambda: tracks.append(1), "params": lambda: params,
              "target_altaz": lambda t: target, "done": lambda result: rig.commits.append(result)})
    with tempfile.TemporaryDirectory() as tmp:
        job = P.Centering(h, "ポルックス", workdir=tmp, settle=0.0, **kw)
        job.start()
        job.thread.join(timeout=30)
        return job.snapshot(), tracks


class CenteringTest(unittest.TestCase):
    def test_converges_despite_positioning_scatter(self):
        rig = SloppyRig()
        target = (87.0, 49.0)
        # モデルは少し外れている（実際の 4 値の残り）
        params = {**TRUE, "az_offset": TRUE["az_offset"] + 0.2, "alt_offset": TRUE["alt_offset"] - 0.15}
        rig.raw = A.axis_of(params, *target)
        status, tracks = center(rig, target, params, tolerance=0.06, rounds=4)
        self.assertIn(status["state"], ("done", "done_warn"), status["message"])
        self.assertGreater(status["rounds"][0]["error"], 0.1)
        final = A.sky_of(TRUE, rig.raw)
        self.assertLess(A.separation(final["az"], final["alt"], *target), 0.36)
        self.assertGreaterEqual(len(tracks), 2)  # 導入のあとと、寄せるたびに追尾を始める

    def test_exact_rig_finishes_in_one_move(self):
        rig = FakeRig()
        target = (87.0, 49.0)
        params = {**TRUE, "az_offset": TRUE["az_offset"] + 0.3}
        rig.raw = A.axis_of(params, *target)
        status, _ = center(rig, target, params, tolerance=0.01)
        self.assertEqual(status["state"], "done", status["message"])
        self.assertEqual(len(status["rounds"]), 2)
        self.assertLess(status["rounds"][-1]["error"], 0.01)

    def test_unsolved_keeps_model_position(self):
        rig = FakeRig(fail_az=[87.0])
        target = (87.0, 49.0)
        rig.raw = A.axis_of(TRUE, *target)
        status, tracks = center(rig, target, TRUE)
        self.assertEqual(status["state"], "unsolved")
        self.assertEqual(rig.moves, [])
        self.assertEqual(len(tracks), 1)

    def test_refuses_huge_correction(self):
        rig = FakeRig()
        target = (87.0, 49.0)
        params = {**TRUE, "az_offset": TRUE["az_offset"] + 5.0}
        rig.raw = A.axis_of(params, *target)
        status, _ = center(rig, target, params)
        self.assertEqual(status["state"], "unsolved")
        self.assertEqual(rig.moves, [])


if __name__ == "__main__":
    unittest.main()
