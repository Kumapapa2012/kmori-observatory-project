#!/usr/bin/env python3
"""映像補正の計算を確かめる。実機とカメラには接続しない。"""
import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.guiding import (HEIGHT, MIN_PEAK, REFRESH_RANGE, WIDTH, Controller, Guider, apply_correction,
                                 field_rotation_rate, measure_shift, refresh_interval)


def scene(seed=1):
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, (HEIGHT * 2, WIDTH * 2))
    spectrum = np.fft.rfft2(base)
    fy = np.fft.fftfreq(HEIGHT * 2)[:, None]
    fx = np.fft.rfftfreq(WIDTH * 2)[None, :]
    spectrum *= np.exp(-(fx ** 2 + fy ** 2) / (2 * 0.03 ** 2))
    image = np.fft.irfft2(spectrum, s=base.shape)
    return (image - image.min()) / (image.max() - image.min()) * 200


def crop(image, dx=0, dy=0):
    x, y = WIDTH // 2 - dx, HEIGHT // 2 - dy
    return image[y:y + HEIGHT, x:x + WIDTH].astype(np.float32)


class MeasureTest(unittest.TestCase):
    def test_finds_known_shift(self):
        image = scene()
        dx, dy, peak = measure_shift(crop(image), crop(image, 17, -9))
        self.assertEqual((dx, dy), (17, -9))
        self.assertGreater(peak, MIN_PEAK)

    def test_zero_shift(self):
        image = scene()
        self.assertEqual(measure_shift(crop(image), crop(image))[:2], (0, 0))

    def test_unrelated_images_have_a_low_peak(self):
        same = measure_shift(crop(scene(1)), crop(scene(1), 5, 5))[2]
        other = measure_shift(crop(scene(1)), crop(scene(2)))[2]
        self.assertLess(other, same / 2)

    def test_tolerates_noise(self):
        image = scene()
        rng = np.random.default_rng(3)
        noisy = crop(image, -11, 6) + rng.normal(0, 15, (HEIGHT, WIDTH)).astype(np.float32)
        self.assertEqual(measure_shift(crop(image), noisy)[:2], (-11, 6))


class ControllerTest(unittest.TestCase):
    def test_right_shift_moves_azimuth_forward(self):
        self.assertGreater(Controller().update(30.0, 0.0, 1.0)["az"], 0)

    def test_down_shift_moves_altitude_backward(self):
        self.assertLess(Controller().update(0.0, 30.0, 1.0)["alt"], 0)

    def test_small_shift_is_ignored(self):
        self.assertEqual(Controller(dead_band=2.0).update(1.0, -1.0, 1.0), {"az": 0.0, "alt": 0.0})

    def test_output_is_limited(self):
        c = Controller(limit=5.0)
        for _ in range(100):
            out = c.update(5000.0, 5000.0, 1.0)
        self.assertEqual(out, {"az": 5.0, "alt": -5.0})

    def test_azimuth_scales_with_altitude(self):
        low = Controller().update(30.0, 0.0, 1.0)["az"]
        high = Controller().update(30.0, 0.0, 0.5)["az"]
        self.assertAlmostEqual(high, low * 2)

    def test_hold_keeps_only_the_integral(self):
        c = Controller()
        c.update(30.0, 0.0, 1.0)
        integral = c.integral["az"]
        c.hold()
        self.assertEqual(c.output["az"], integral)

    def test_constant_drift_converges(self):
        c = Controller()
        drift, position = 0.5, 0.0  # 秒角/秒
        for _ in range(60):
            out = c.update(position, 0.0, 1.0)
            position += (drift - out["az"]) * c.period
        self.assertAlmostEqual(out["az"], drift, delta=0.1)
        self.assertLess(abs(position), 4.0)


class CorrectionTest(unittest.TestCase):
    def test_adds_correction(self):
        self.assertEqual(apply_correction(10.0, 1.5), 11.5)

    def test_does_not_reverse_direction(self):
        self.assertEqual(apply_correction(1.0, -3.0), 0.0)
        self.assertEqual(apply_correction(-1.0, 3.0), 0.0)


class RotationTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(field_rotation_rate(35.7, 75.0, 5.0), 3.17, delta=0.05)
        self.assertAlmostEqual(field_rotation_rate(35.7, 180.0, 60.0), 24.4, delta=0.2)
        self.assertAlmostEqual(field_rotation_rate(35.7, 90.0, 40.0), 0.0, delta=0.01)

    def test_interval_shrinks_with_rotation(self):
        self.assertEqual(refresh_interval(0.0), REFRESH_RANGE[1])
        self.assertEqual(refresh_interval(1.0), REFRESH_RANGE[1])
        self.assertAlmostEqual(refresh_interval(10.0), 90.0, delta=0.1)
        self.assertEqual(refresh_interval(24.4), REFRESH_RANGE[0])
        self.assertEqual(refresh_interval(1000.0), REFRESH_RANGE[0])


class FakeReader:
    def __init__(self, image):
        self.image = image
        self.drift = 0.0
        self.opened = 0
        self.start = time.monotonic()

    def open(self):
        self.opened += 1

    def read(self):
        time.sleep(0.01)
        return crop(self.image, int((time.monotonic() - self.start) * self.drift), 0)

    def close(self):
        pass


class GuiderTest(unittest.TestCase):
    def setUp(self):
        self.reader = FakeReader(scene())
        self.ctx = {"paused": False, "mode": "live", "cos_alt": 1.0, "rotation": 0.0}
        self.guider = Guider(self.reader, lambda: self.ctx, period=0.2, window=0.05, settle=0.02)

    def tearDown(self):
        self.guider.stop()

    def wait_state(self, state):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if self.guider.snapshot()["state"] == state:
                return
            time.sleep(0.01)
        self.fail(self.guider.snapshot())

    def test_drift_produces_correction(self):
        self.reader.drift = 50.0
        self.guider.start()
        self.wait_state("guiding")
        time.sleep(0.8)
        snap = self.guider.snapshot()
        self.assertGreater(snap["error_x"], 0)
        self.assertGreater(snap["correction"]["az"], 0)

    def test_pause_is_reported_and_resumes(self):
        self.guider.start()
        self.wait_state("guiding")
        self.ctx["paused"] = True
        self.wait_state("paused")
        self.ctx["paused"] = False
        self.wait_state("guiding")

    def test_unrelated_view_is_rejected(self):
        self.guider.start()
        self.wait_state("guiding")
        other = scene(9)
        self.reader.read = lambda: (time.sleep(0.01), crop(other))[1]
        self.wait_state("lost")

    def test_stop_clears_correction(self):
        self.reader.drift = 50.0
        self.guider.start()
        time.sleep(0.5)
        self.guider.stop()
        snap = self.guider.snapshot()
        self.assertEqual(snap["state"], "off")
        self.assertEqual(snap["correction"], {"az": 0.0, "alt": 0.0})


if __name__ == "__main__":
    unittest.main()
