#!/usr/bin/env python3
"""直結版の架台（direct_mount.py）と安全装置（safety.py）を疑似の基板で確かめる。実機には接続しない。"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_motor import CPR, FakeMotorBoard
from observatory.direct_mount import DirectMount
from observatory.motor import MotorBoard, MotorError
from observatory.mount import MountError
from observatory.safety import (Envelope, Monitor, Reference, SafetyConfig, SafetyError, angular_separation,
                                check_sun, power_on_reference)

K = CPR / 360.0


def wait_for(cond, timeout=3.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False


class MotorBoardTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMotorBoard(initialized=True)
        self.board = MotorBoard("fake", link=self.fake)

    def test_reads(self):
        self.assertEqual(self.board.version(), ("2.09", 0xA1))
        self.assertEqual(self.board.cpr("az"), CPR)
        self.assertEqual(self.board.timer_freq(), 20000)
        self.assertEqual(self.board.position("alt"), 0)
        self.assertTrue(self.board.status("az")["initialized"])

    def test_garbled_reply_is_retried_once(self):
        self.fake.garble = 1
        self.assertEqual(self.board.position("az"), 0)
        self.assertEqual(self.board.bad_replies, 1)

    def test_garbled_twice_raises(self):
        self.fake.garble = 2
        with self.assertRaises(MotorError):
            self.board.position("az")

    def test_board_refusal_raises(self):
        self.board.set_motion("az", "1", True)
        self.board.set_period("az", 1000)
        self.board.start("az")
        with self.assertRaises(MotorError):
            self.board.set_motion("az", "1", False)


class SafetyTest(unittest.TestCase):
    def test_no_reference_uses_power_on_pose_by_default(self):
        env = Envelope(SafetyConfig())  # 制限モードは既定で無効
        self.assertFalse(env.referenced)
        self.assertFalse(env.restricted)
        self.assertEqual(env.axis_range("az"), (-180.0, 180.0))
        self.assertEqual(env.axis_range("alt"), (-5.0, 92.0))
        self.assertEqual(env.max_rate(), 3.0)
        with self.assertRaises(SafetyError):
            env.check_target("alt", 93.0)

    def test_restricted_until_reference(self):
        env = Envelope(SafetyConfig(restricted_mode=True))
        self.assertTrue(env.restricted)
        self.assertEqual(env.axis_range("az"), (-30.0, 30.0))
        self.assertEqual(env.axis_range("alt"), (-20.0, 20.0))
        self.assertEqual(env.max_rate(), 0.3)
        with self.assertRaises(SafetyError):
            env.check_target("az", 31.0)
        env.reference = power_on_reference()
        self.assertFalse(env.restricted)
        self.assertEqual(env.axis_range("alt"), (-5.0, 92.0))
        self.assertEqual(env.axis_range("az"), (-180.0, 180.0))

    def test_landmark_reference_shifts_alt_range(self):
        env = Envelope(SafetyConfig(), Reference(kind="landmark", az_offset=116.0, alt_offset=3.0))
        self.assertEqual(env.axis_range("alt"), (-8.0, 89.0))
        self.assertEqual(env.axis_range("az"), (-180.0, 180.0))

    def test_sun(self):
        cfg = SafetyConfig()
        ref = power_on_reference()
        with self.assertRaises(SafetyError):
            check_sun(cfg, ref, {"az": 100.0, "alt": 20.0}, (105.0, 25.0))
        check_sun(cfg, ref, {"az": 100.0, "alt": 20.0}, (150.0, 25.0))
        check_sun(cfg, Reference(), {"az": 100.0, "alt": 20.0}, (100.0, 20.0))  # 未確定では判断しない
        self.assertAlmostEqual(angular_separation(0, 0, 90, 0), 90.0)

    def test_monitor(self):
        cfg = SafetyConfig()
        st = {"initialized": True, "running": False}
        m = Monitor(cfg)
        self.assertIsNone(m.update({"az": 0, "alt": 0}, {"az": st, "alt": st}, {}, 0.0))
        self.assertIsNone(m.update({"az": 0.01, "alt": 0}, {"az": st, "alt": st}, {}, 0.2))
        self.assertIn("止めているのに", m.update({"az": 0.2, "alt": 0}, {"az": st, "alt": st}, {}, 0.4))
        m = Monitor(cfg)
        m.update({"az": 0, "alt": 0}, {"az": st, "alt": st}, {"az": 1.0}, 0.0)
        self.assertIn("飛んだ", m.update({"az": 3.0, "alt": 0}, {"az": st, "alt": st}, {"az": 1.0}, 0.2))
        m = Monitor(cfg)
        bad = {"initialized": False, "running": False}
        self.assertIn("未初期化", m.update({"az": 0, "alt": 0}, {"az": bad, "alt": st}, {}, 0.0))
        m = Monitor(cfg)
        run = {"initialized": True, "running": True}
        for i in range(15):
            r = m.update({"az": 0, "alt": 0}, {"az": run, "alt": st}, {"az": 0.5}, i * 0.2)
        self.assertIn("変わらない", r)
        m = Monitor(cfg)
        self.assertIsNone(m.read_failed())
        self.assertIsNone(m.read_failed())
        self.assertIn("3 回", m.read_failed())


class DirectMountTest(unittest.TestCase):
    def make(self, initialized=False, reference=None, **cfg):
        self.fake = FakeMotorBoard(initialized=initialized)
        board = MotorBoard("fake", link=self.fake)
        self.mount = DirectMount("fake", cfg, board=board, reference=reference, poll_interval=0.05, hold_timeout=0.3)
        self.addCleanup(self.close)
        return self.mount

    def close(self):
        try:
            self.mount.close()
        except MountError:
            pass

    def pos(self, axis):
        with self.fake.lock:
            self.fake.advance()
            return self.fake.axes["1" if axis == "az" else "2"].pos / K

    def test_connect_initializes_without_moving(self):
        m = self.make(initialized=False)
        self.assertTrue(m.fresh_power_on)
        self.assertTrue(all(a.initialized for a in self.fake.axes.values()))
        moves = [c for a in self.fake.axes.values() for c in a.commands if c[0] in "GJH"]
        self.assertEqual(moves, [])
        self.assertFalse(m.status()["referenced"])
        self.assertFalse(m.status()["restricted"])

    def test_wrong_cpr_refuses(self):
        self.fake = FakeMotorBoard()
        with self.assertRaises(MountError):
            DirectMount("fake", {"expected_cpr": 1000}, board=MotorBoard("fake", link=self.fake))

    def test_hold_timeout_stops(self):
        m = self.make(reference=power_on_reference())
        m.move("az", 1, 7)
        self.assertTrue(wait_for(lambda: self.pos("az") > 0.05))
        self.assertTrue(wait_for(lambda: not m.status()["moving"], timeout=2))
        self.assertFalse(self.fake.axes["1"].running)
        self.assertIn("途切れた", m.status()["message"])

    def test_restricted_mode_caps_speed_and_range(self):
        m = self.make(safety={"restricted_mode": True})
        self.assertAlmostEqual(m.speed(9), 0.3)
        self.fake.axes["1"].pos = 29.9 * K
        m.monitor.last = None
        time.sleep(0.15)
        with self.assertRaises(MountError):  # 範囲の端で止め、向きをロックする
            m.move("az", 1, 9)
            for _ in range(40):
                time.sleep(0.05)
                m.move("az", 1, 9)
        self.assertLess(self.pos("az"), 30.1)

    def test_no_reference_moves_past_restricted_range(self):
        m = self.make()  # 基準なし、制限モードは無効
        self.fake.axes["1"].pos = 29.9 * K
        m.monitor.last = None
        time.sleep(0.15)
        for _ in range(10):
            m.move("az", 1, 9)
            time.sleep(0.05)
        self.assertTrue(wait_for(lambda: self.pos("az") > 30.5))
        m.stop()

    def test_range_end_stops_while_moving(self):
        m = self.make(reference=power_on_reference())
        self.fake.axes["2"].pos = 91.5 * K
        m.monitor.last = None
        time.sleep(0.15)
        end = time.monotonic() + 2
        while time.monotonic() < end and not m.status()["moving"] == {} or time.monotonic() < end - 1.8:
            try:
                m.move("alt", 1, 7)
            except MountError:
                break
            time.sleep(0.05)
        self.assertTrue(wait_for(lambda: not self.fake.axes["2"].running))
        self.assertLess(self.pos("alt"), 92.05)

    def test_direction_change_takes_up_gap(self):
        m = self.make(reference=power_on_reference())
        m.move("az", -1, 3)  # 0.036°/秒。隙間が残っているので最初は 0.3°/秒で詰める
        self.assertTrue(m.moves["az"]["taking_up"])
        self.assertTrue(wait_for(lambda: not m.moves.get("az", {"taking_up": False})["taking_up"], timeout=2))
        m.drive(0, 0)
        self.assertTrue(wait_for(lambda: not self.fake.axes["1"].running))

    def test_goto_finishes_from_plus_side(self):
        m = self.make(reference=power_on_reference())
        m.goto_axes({"az": -2.0}, "テスト")
        self.assertTrue(wait_for(lambda: m.status()["goto"] is None, timeout=15))
        self.assertTrue(m.status()["goto_result"]["ok"])
        self.assertAlmostEqual(self.pos("az"), -2.0, delta=0.01)
        cmds = [c for c in self.fake.axes["1"].commands if c.startswith("G")]
        self.assertEqual(cmds[-1][2], "0")  # 最後の区間は + 向き

    def test_goto_rejects_over_limit(self):
        m = self.make(reference=power_on_reference())
        with self.assertRaises(SafetyError):
            m.goto_axes({"az": 50.0})
        with self.assertRaises(SafetyError):
            m.goto_axes({"alt": 93.0})
        self.assertIsNone(m.status()["goto"])

    def test_unexpected_motion_stops_and_latches(self):
        m = self.make(reference=power_on_reference())
        time.sleep(0.2)
        self.fake.external_move("1", 0.2 * K)
        self.assertTrue(wait_for(lambda: m.status()["fault"] != ""))
        with self.assertRaises(MountError):
            m.move("az", 1, 3)
        m.stop()  # 停止ボタンで解除
        self.assertEqual(m.status()["fault"], "")
        m.move("az", 1, 3)

    def test_power_glitch_returns_to_restricted(self):
        m = self.make(reference=power_on_reference())
        time.sleep(0.2)
        self.fake.power_glitch()
        self.assertTrue(wait_for(lambda: "未初期化" in m.status()["fault"]))
        self.assertFalse(m.status()["referenced"])
        m.stop()
        self.assertTrue(all(a.initialized for a in self.fake.axes.values()))

    def test_read_failures_stop(self):
        m = self.make(reference=power_on_reference())
        m.move("az", 1, 5)
        self.fake.silent = True
        time.sleep(0.4)
        self.fake.silent = False
        self.assertTrue(wait_for(lambda: "失敗" in m.status()["fault"] or not self.fake.axes["1"].running))

    def test_tracking_and_rate_limit(self):
        m = self.make(reference=power_on_reference())
        m.track({"az": 15.0, "alt": -10.0})
        self.assertTrue(self.fake.axes["1"].running and not self.fake.axes["2"].forward)
        m.update_track({"az": 20.0, "alt": 5.0})
        self.assertTrue(self.fake.axes["2"].forward)
        with self.assertRaises(SafetyError):
            m.track({"az": 3600.0})
        m.stop()
        self.assertFalse(any(a.running for a in self.fake.axes.values()))

    def test_unplugged_usb_sets_error(self):
        m = self.make(reference=power_on_reference())

        def broken(*a):
            raise OSError(5, "Input/output error")
        self.fake.reset_input_buffer = broken
        self.assertTrue(wait_for(lambda: m.status()["error"] != ""))
        self.assertTrue(m.thread.is_alive())

    def test_synscan_features_absent(self):
        m = self.make()
        self.assertFalse(m.synscan_aligned())
        self.assertEqual(m.tracking_mode(), "off")
        m.set_tracking_mode("off")
        with self.assertRaises(MountError):
            m.set_tracking_mode("altaz")


if __name__ == "__main__":
    unittest.main()
