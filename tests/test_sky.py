#!/usr/bin/env python3
"""天体の指定（名前、赤経・赤緯）と、自動導入の計画を確かめる。実機には接続しない。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from skyfield.api import Star

from observatory.app import GOTO_MAX_DEG, describe_plan, goto_plan
from observatory.sky import Sky, TargetError, format_radec, parse_radec, resolve

ALCYONE = (3 + 47 / 60 + 29.08 / 3600, 24 + 6 / 60 + 18.5 / 3600)
M1 = (5 + 34 / 60 + 31.94 / 3600, 22 + 0 / 60 + 52.2 / 3600)


class ParseRaDecTest(unittest.TestCase):
    def assertRaDec(self, text, expected, places=6):
        ra, dec = parse_radec(text)
        self.assertAlmostEqual(ra, expected[0], places=places)
        self.assertAlmostEqual(dec, expected[1], places=places)

    def test_hms_dms(self):
        self.assertRaDec("3h47m29.08s +24°06'18.5\"", ALCYONE)
        self.assertRaDec("RA 5h34m31.94s Dec +22°00'52.2\"", M1)

    def test_prime_marks_and_full_width(self):
        self.assertRaDec("5h34m31.94s +22°00′52.2″", M1)
        self.assertRaDec("５h３４m３１.９４s　＋２２°００'５２.２\"", M1)

    def test_colons_and_spaces(self):
        self.assertRaDec("03:47:29.08 +24:06:18.5", ALCYONE)
        self.assertRaDec("3 47 29.08 24 06 18.5", ALCYONE)

    def test_decimal_degrees(self):
        self.assertRaDec("56.871167 24.105139", ALCYONE, places=5)
        self.assertRaDec("83.82,-5.39", (83.82 / 15, -5.39))

    def test_negative_declination(self):
        self.assertRaDec("5h35m17.3s -5°23'28\"", (5 + 35 / 60 + 17.3 / 3600, -(5 + 23 / 60 + 28 / 3600)))
        self.assertRaDec("05 35 17.3 -05 23 28", (5 + 35 / 60 + 17.3 / 3600, -(5 + 23 / 60 + 28 / 3600)))
        self.assertRaDec("5h35m17.3s −0°23'28\"", (5 + 35 / 60 + 17.3 / 3600, -(23 / 60 + 28 / 3600)))

    def test_rejects_bad_values(self):
        for text in ("25h00m 10", "3h47m +95", "3h99m 10 10", "abc def", "3h47m"):
            with self.subTest(text=text), self.assertRaises(TargetError):
                parse_radec(text)

    def test_format_rounds_without_sixty(self):
        self.assertEqual(format_radec(*ALCYONE), "3h47m29.08s +24°06'18.5\"")
        self.assertEqual(format_radec(1 - 1e-9, -0.5), "1h00m00.00s -00°30'00.0\"")


class ResolveTest(unittest.TestCase):
    def test_names_and_aliases(self):
        for query, key in (("Pleiades", "alcyone"), ("M45", "alcyone"), ("すばる", "alcyone"), ("m1", "m1"),
                           ("M 1", "m1"), ("Crab", "m1"), ("Uranus", "uranus"), ("天王星", "uranus"),
                           ("vega", "vega"), ("シリウス", "sirius")):
            with self.subTest(query=query):
                self.assertEqual(resolve(query)["key"], key)

    def test_coordinates(self):
        target = resolve("5h34m31.94s +22°00'52.2\"")
        self.assertEqual(target["kind"], "coords")
        self.assertAlmostEqual(target["ra_hours"], M1[0])
        self.assertIsInstance(target["object"], Star)

    def test_unknown_name(self):
        with self.assertRaises(TargetError):
            resolve("unknown object")
        with self.assertRaises(TargetError):
            resolve("")


class SkyTargetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sky = Sky(35.733319, 139.753847, 92.2)
        cls.time = cls.sky.timescale.utc(2026, 11, 7, 12, 39)  # 21:39 JST

    def test_coordinates_and_catalog_give_the_same_position(self):
        a = self.sky.altaz("m1", self.time)
        b = self.sky.altaz(resolve("5h34m31.94s +22°00'52.2\""), self.time)
        self.assertAlmostEqual(a[0], b[0], places=6)
        self.assertAlmostEqual(a[1], b[1], places=6)
        # かに星雲は 21:39 JST に高度 30° 付近まで昇る
        self.assertAlmostEqual(a[1], 30.0, delta=1.5)

    def test_star_j2000_is_the_catalog_position(self):
        ra, dec = self.sky.radec_j2000("alcyone", self.time)
        self.assertAlmostEqual(ra, ALCYONE[0], delta=1 / 3600 / 15)
        self.assertAlmostEqual(dec, ALCYONE[1], delta=1 / 3600)

    def test_planet_rates(self):
        az, alt = self.sky.altaz("uranus", self.time)
        rate_az, rate_alt = self.sky.rates("uranus", self.time)
        self.assertTrue(alt > 0)
        self.assertLess(abs(rate_az) + abs(rate_alt), 40.0)


class GotoPlanTest(unittest.TestCase):
    OFFSET = {"az": 0.0, "alt": 0.0}
    LIMITS = {"az": 180.0, "alt": 90.0}

    def test_short_way_round(self):
        plan = goto_plan({"az": 350.0, "alt": 40.0}, {"az": 10.0, "alt": 30.0}, self.OFFSET, self.LIMITS, "M1")
        self.assertEqual(plan["az_direction"], 1)
        self.assertAlmostEqual(plan["az_amount"], 20.0)
        self.assertAlmostEqual(plan["d_alt"], -10.0)
        self.assertEqual(plan["alt_range"], [25.0, 45.0])
        self.assertIn("東回り", describe_plan(plan))

    def test_west(self):
        plan = goto_plan({"az": 92.0, "alt": 47.0}, {"az": 80.0, "alt": 30.0}, self.OFFSET, self.LIMITS, "M1")
        self.assertEqual(plan["az_direction"], -1)
        self.assertIn("西回り", describe_plan(plan))

    def test_refuses_large_moves(self):
        with self.assertRaises(TargetError):
            goto_plan({"az": 0.0, "alt": 40.0}, {"az": GOTO_MAX_DEG + 1, "alt": 40.0}, self.OFFSET, self.LIMITS, "x")
        with self.assertRaises(TargetError):
            goto_plan({"az": 0.0, "alt": 12.0}, {"az": 0.0, "alt": 12.0 + GOTO_MAX_DEG + 1}, self.OFFSET, self.LIMITS, "x")

    def test_refuses_low_and_high_targets(self):
        with self.assertRaises(TargetError):
            goto_plan({"az": 0.0, "alt": 20.0}, {"az": 5.0, "alt": 5.0}, self.OFFSET, self.LIMITS, "x")
        with self.assertRaises(TargetError):
            goto_plan({"az": 0.0, "alt": 60.0}, {"az": 5.0, "alt": 85.0}, self.OFFSET, self.LIMITS, "x")

    def test_refuses_past_the_range_limit(self):
        with self.assertRaises(TargetError):
            goto_plan({"az": 0.0, "alt": 40.0}, {"az": 30.0, "alt": 40.0}, {"az": 160.0, "alt": 0.0}, self.LIMITS, "x")


if __name__ == "__main__":
    unittest.main()
