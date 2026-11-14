#!/usr/bin/env python3
"""観測地の入力の確認と、観測地の変更を確かめる。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.app import parse_elevation, parse_geoid, parse_site
from observatory.sky import Sky


class ParseSiteTest(unittest.TestCase):
    def test_phone(self):
        site = parse_site({"latitude": "35.71", "longitude": 139.81, "elevation_m": 45,
                           "source": "phone", "accuracy_m": 4.2})
        self.assertEqual(site, {"latitude": 35.71, "longitude": 139.81, "elevation_m": 45.0,
                                "source": "phone", "accuracy_m": 4.2})

    def test_defaults_to_manual(self):
        site = parse_site({"latitude": 35.0, "longitude": 139.0, "source": "other"})
        self.assertEqual(site["source"], "manual")
        self.assertEqual(site["elevation_m"], 0.0)
        self.assertNotIn("accuracy_m", site)

    def test_rejects(self):
        for body in [{}, {"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": 181},
                     {"latitude": "nan", "longitude": 0}, {"latitude": 0, "longitude": 0, "elevation_m": 10000},
                     {"latitude": None, "longitude": 0}]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_site(body)


    def test_map_with_breakdown(self):
        site = parse_site({"latitude": 35.73338, "longitude": 139.753726, "elevation_m": 91.1, "source": "map",
                           "ground_m": 12.9, "height_m": 41, "geoid_m": 37.1925, "accuracy_m": True})
        self.assertEqual(site["source"], "map")
        self.assertEqual((site["ground_m"], site["height_m"], site["geoid_m"]), (12.9, 41.0, 37.1925))
        self.assertNotIn("accuracy_m", site)


class GsiResponseTest(unittest.TestCase):
    # 2026-11-07 に実際に取得した応答
    ELEVATION = '{"elevation":12.9,"hsrc":"1m\\uff08\\u30ec\\u30fc\\u30b6\\uff09"}'
    GEOID = ('{"OutputData":{"latitude":"35.733380000","longitude":"139.753726000","geoidHeight":"37.1925",'
             '"HeightReferenceConversion":"0.0000","geoidHeight+HeightReferenceConversion":"37.1925"}}')

    def test_elevation(self):
        self.assertEqual(parse_elevation(self.ELEVATION), (12.9, "1m（レーザ）"))

    def test_elevation_unavailable(self):
        for text in ['{"elevation":"-----","hsrc":"-----"}', "<html>", "{}", "null"]:
            with self.subTest(text=text):
                self.assertEqual(parse_elevation(text), (None, None))

    def test_geoid(self):
        self.assertEqual(parse_geoid(self.GEOID), 37.1925)

    def test_geoid_unavailable(self):
        for text in ['{"OutputData":{"geoidHeight":"nan"}}', '{"OutputData":{}}', "<html>", "[]"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_geoid(text))


class SetSiteTest(unittest.TestCase):
    def test_polaris_altitude_follows_latitude(self):
        sky = Sky(35.0, 139.0)
        time = sky.now()
        _, alt_south = sky.altaz("polaris", time, refraction=False)
        sky.set_site(36.0, 139.0)
        _, alt_north = sky.altaz("polaris", time, refraction=False)
        self.assertAlmostEqual(alt_north - alt_south, 1.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
