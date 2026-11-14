#!/usr/bin/env python3
"""校正の計算を確かめる。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.alignment import pointing, register, still_valid, wrap180


class AlignmentTest(unittest.TestCase):
    def test_registered_position_is_reported_back(self):
        a = register("polaris", (0.5, 36.0), {"az": 10.0, "alt": 5.0}, 1000.0, now=2000.0)
        p = pointing(a, {"az": 10.0, "alt": 5.0})
        self.assertAlmostEqual(p["az"], 0.5)
        self.assertAlmostEqual(p["alt"], 36.0)

    def test_motion_is_added_to_the_pointing(self):
        a = register("polaris", (0.5, 36.0), {"az": 10.0, "alt": 5.0}, 1000.0, now=2000.0)
        p = pointing(a, {"az": 40.0, "alt": 15.0})
        self.assertAlmostEqual(p["az"], 30.5)
        self.assertAlmostEqual(p["alt"], 46.0)

    def test_azimuth_wraps_through_north(self):
        a = register("polaris", (359.5, 36.0), {"az": 1.0, "alt": 0.0}, 0.0, now=0.0)
        self.assertAlmostEqual(a["az_offset"], -1.5)
        self.assertAlmostEqual(pointing(a, {"az": 2.0, "alt": 0.0})["az"], 0.5)
        self.assertAlmostEqual(pointing(a, {"az": 0.0, "alt": 0.0})["az"], 358.5)

    def test_encoder_near_full_circle_is_treated_as_negative_altitude(self):
        a = register("polaris", (0.0, 36.0), {"az": 0.0, "alt": 359.42}, 0.0, now=0.0)
        self.assertAlmostEqual(pointing(a, {"az": 0.0, "alt": 0.0})["alt"], 36.58)

    def test_clock_detects_power_cycle(self):
        a = register("polaris", (0.0, 36.0), {"az": 0.0, "alt": 0.0}, 1000.0, now=5000.0)
        self.assertTrue(still_valid(a, 1600.0, now=5600.0))
        self.assertTrue(still_valid(a, 1610.0, now=5600.0))
        self.assertFalse(still_valid(a, 1000.0, now=5600.0))

    def test_wrap180(self):
        self.assertAlmostEqual(wrap180(350.0), -10.0)
        self.assertAlmostEqual(wrap180(-190.0), 170.0)


if __name__ == "__main__":
    unittest.main()
