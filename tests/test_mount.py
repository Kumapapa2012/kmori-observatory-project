#!/usr/bin/env python3
"""mount.py の安全処理を疑似シリアルで確かめる。実機には接続しない。"""
import os
import pty
import sys
import threading
import time
import tty
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.mount import Mount, MountError


class FakeSynScan(threading.Thread):
    """P と z だけに応答する SynScan の代役。速度に比例して位置が進む。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.master, slave = pty.openpty()
        tty.setraw(self.master)
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        self.slave = slave
        self.rates = {16: 0.0, 17: 0.0}
        self.position = {16: 0.0, 17: 0.0}
        self.speed = 0.0  # 速度 1 あたりの度/秒
        self.silent = False
        self.aligned = 0  # SynScan 本体のアライメント（J の応答）
        self.flip_reporting = False  # 実機と同じく、高度が 90〜270° の間は裏返して返す
        self.lock = threading.Lock()
        self.last = time.monotonic()
        # 自動導入（r）の代役。goto_velocity（度/秒）で goto_seconds の間動く
        self.goto_velocity = {16: 0.0, 17: 0.0}
        self.goto_seconds = 0.0
        self.goto_until = 0.0
        self.goto_started = 0.0
        self.goto_idle_until = 0.0  # 開始からこの秒数の間は、動いていても L が 0 を返す
        self.goto_commands = []
        self.cancels = 0
        self.tracking_mode = 0
        self.tracking_commands = []

    def _advance(self):
        now = time.monotonic()
        for axis in self.rates:
            self.position[axis] += self.rates[axis] * self.speed * (now - self.last)
            moving = max(0.0, min(now, self.goto_until) - self.last)
            self.position[axis] += self.goto_velocity[axis] * moving
        self.last = now

    def run(self):
        while True:
            data = os.read(self.master, 1)
            if data == b"P":
                body = b""
                while len(body) < 7:
                    body += os.read(self.master, 7 - len(body))
                with self.lock:
                    self._advance()
                    sign = 1 if body[2] in (36, 6) else -1
                    rate = (body[3] << 8 | body[4]) / 4 if body[0] == 3 else body[3]
                    self.rates[body[1]] = sign * rate
                if not self.silent:
                    os.write(self.master, b"#")
            elif data == b"r":
                body = b""
                while len(body) < 17:
                    body += os.read(self.master, 17 - len(body))
                with self.lock:
                    self._advance()
                    self.goto_commands.append(body.decode())
                    self.goto_started = time.monotonic()
                    self.goto_until = self.goto_started + self.goto_seconds
                os.write(self.master, b"#")
            elif data == b"L":
                with self.lock:
                    self._advance()
                    now = time.monotonic()
                    busy = now < self.goto_until and now - self.goto_started >= self.goto_idle_until
                os.write(self.master, (b"1" if busy else b"0") + b"#")
            elif data == b"M":
                with self.lock:
                    self._advance()
                    self.goto_until = 0.0
                    self.cancels += 1
                os.write(self.master, b"#")
            elif data == b"t":
                os.write(self.master, bytes([self.tracking_mode]) + b"#")
            elif data == b"T":
                mode = os.read(self.master, 1)[0]
                self.tracking_mode = mode
                self.tracking_commands.append(mode)
                os.write(self.master, b"#")
            elif data == b"J":
                if not self.silent:
                    os.write(self.master, bytes([self.aligned]) + b"#")
            elif data == b"h":
                if not self.silent:
                    os.write(self.master, bytes([20, 0, 5, 7, 31, 18, 9, 0]) + b"#")
            elif data == b"z":
                with self.lock:
                    self._advance()
                    az_deg, alt_deg = self.position[16] % 360, self.position[17] % 360
                    if self.flip_reporting and 90 < alt_deg < 270:
                        az_deg, alt_deg = (az_deg + 180) % 360, (180 - alt_deg) % 360
                    az, alt = (int(v / 360 * 2 ** 32) & 0xFFFFFFFF for v in (az_deg, alt_deg))
                if not self.silent:
                    os.write(self.master, f"{az:08X},{alt:08X}#".encode())


class MountTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSynScan()
        self.fake.start()
        self.mount = Mount(self.fake.port, az_limit=5.0, alt_limit=5.0, hold_timeout=0.4, poll_interval=0.05)

    def tearDown(self):
        self.fake.silent = False
        self.mount.close()

    def test_move_and_stop(self):
        self.mount.move("az", 1, 3)
        self.assertEqual(self.fake.rates[16], 3)
        self.mount.stop()
        self.assertEqual(self.fake.rates, {16: 0, 17: 0})

    def test_reverse_direction(self):
        self.mount.move("alt", -1, 2)
        self.assertEqual(self.fake.rates[17], -2)

    def test_stops_when_heartbeat_ends(self):
        self.mount.move("az", 1, 3)
        time.sleep(0.8)
        self.assertEqual(self.fake.rates[16], 0)
        self.assertIn("途切れ", self.mount.status()["message"])

    def test_heartbeat_keeps_moving(self):
        for _ in range(8):
            self.mount.move("az", 1, 3)
            time.sleep(0.1)
        self.assertEqual(self.fake.rates[16], 3)

    def test_late_hold_after_stop_does_not_restart(self):
        self.mount.move("az", 1, 3)
        self.mount.stop()
        self.mount.move("az", 1, 3, start=False)
        self.assertEqual(self.fake.rates[16], 0)
        self.assertEqual(self.mount.status()["moving"], {})

    def test_drive_moves_both_axes_and_stops_each(self):
        self.mount.drive(3, -2)
        self.assertEqual(self.fake.rates, {16: 3, 17: -2})
        self.mount.drive(0, -2)
        self.assertEqual(self.fake.rates, {16: 0, 17: -2})
        self.mount.drive(0, 0)
        self.assertEqual(self.fake.rates, {16: 0, 17: 0})
        self.assertEqual(self.mount.status()["moving"], {})

    def test_reads_clock_and_raw_position(self):
        self.assertEqual(self.mount.clock(), 1533067205)
        self.assertEqual(set(self.mount.status()["raw"]), {"az", "alt"})

    def test_rejects_rate_above_maximum(self):
        with self.assertRaises(ValueError):
            self.mount.move("az", 1, 9)
        self.assertEqual(self.fake.rates[16], 0)

    def test_stops_at_limit_and_allows_return(self):
        self.fake.speed = 10.0
        for _ in range(20):
            try:
                self.mount.move("az", 1, 1)
            except MountError:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        self.assertEqual(self.fake.rates[16], 0)
        self.assertIn("上限", self.mount.status()["message"])
        with self.assertRaises(MountError):
            self.mount.move("az", 1, 1)
        self.mount.move("az", -1, 1)
        self.assertEqual(self.fake.rates[16], -1)

    def test_tracks_position_across_wrap(self):
        self.fake.position[16] = 359.0
        time.sleep(0.2)
        before = self.mount.status()["az"]
        self.fake.position[16] = 1.0
        time.sleep(0.2)
        self.assertAlmostEqual(self.mount.status()["az"] - before, 2.0, places=1)

    def test_reports_error_when_controller_stops_replying(self):
        self.mount.move("az", 1, 3)
        self.fake.silent = True
        time.sleep(1.5)
        self.assertTrue(self.mount.status()["error"])
        self.assertEqual(self.mount.status()["moving"], {})


class TrackingTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSynScan()
        self.fake.start()
        # 範囲の上限の試験で読み取りを一度に 6° 動かすので、飛びの判定を緩める
        self.mount = Mount(self.fake.port, az_limit=5.0, alt_limit=5.0, hold_timeout=0.3, poll_interval=0.05,
                           jump_deg=10.0)

    def tearDown(self):
        self.mount.close()

    def test_sends_signed_rates(self):
        self.mount.track({"az": 15.25, "alt": -7.5})
        self.assertEqual(self.fake.rates, {16: 15.25, 17: -7.5})
        self.assertEqual(self.mount.status()["tracking"], {"az": 15.25, "alt": -7.5})

    def test_update_changes_the_rate(self):
        self.mount.track({"az": 15.0})
        self.mount.update_track({"az": 14.0, "alt": 3.0})
        self.assertEqual(self.fake.rates, {16: 14.0, 17: 0})

    def test_stick_release_returns_to_tracking(self):
        self.mount.track({"az": 15.0})
        self.mount.drive(3, 0)
        self.assertEqual(self.fake.rates[16], 3)
        self.mount.update_track({"az": 16.0})
        self.assertEqual(self.fake.rates[16], 3)
        self.mount.drive(0, 0)
        self.assertEqual(self.fake.rates[16], 16.0)

    def test_stick_timeout_returns_to_tracking(self):
        self.mount.track({"az": 15.0})
        self.mount.drive(3, 0)
        time.sleep(0.6)
        self.assertEqual(self.fake.rates[16], 15.0)

    def test_stop_ends_tracking(self):
        self.mount.track({"az": 15.0, "alt": 5.0})
        self.mount.stop()
        self.assertEqual(self.fake.rates, {16: 0, 17: 0})
        self.assertEqual(self.mount.status()["tracking"], {})

    def test_limit_ends_tracking(self):
        self.fake.position[16] = 6.0
        self.mount.track({"az": 15.0})
        time.sleep(0.3)
        self.assertEqual(self.fake.rates[16], 0)
        self.assertEqual(self.mount.status()["tracking"], {})
        self.assertIn("上限", self.mount.status()["message"])


class BacklashTest(unittest.TestCase):
    CONFIG = {"enabled": True, "speeds": {"1": 0.5, "6": 3.0},
              "az": {"amount": 0.6, "rate": 6, "source": "encoder", "lead": 0.0, "start_delay": 0.0},
              "alt": {"amount": 0.3, "rate": 6, "source": "time", "lead": 0.0, "start_delay": 0.0}}

    def setUp(self):
        self.fake = FakeSynScan()
        self.fake.speed = 0.5
        self.fake.start()
        self.mount = Mount(self.fake.port, az_limit=45.0, alt_limit=45.0, hold_timeout=5.0,
                           poll_interval=0.02, backlash=self.CONFIG)

    def tearDown(self):
        self.mount.close()

    def wait_rate(self, axis, expected, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.fake.rates[axis] == expected:
                return
            time.sleep(0.005)
        self.fail(f"rate {self.fake.rates[axis]} != {expected}")

    def test_takes_up_half_the_gap_after_start(self):
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 6)
        self.wait_rate(16, 1)
        self.assertAlmostEqual(self.mount.gap["az"], 0.6, delta=0.01)

    def test_reversal_takes_up_the_full_gap(self):
        self.mount.move("az", 1, 1)
        self.wait_rate(16, 1)
        start = time.monotonic()
        self.mount.move("az", -1, 1)
        self.assertEqual(self.fake.rates[16], -6)
        self.wait_rate(16, -1)
        # 0.6° を 3°/s で詰めるので約 0.2 秒
        self.assertAlmostEqual(time.monotonic() - start, 0.2, delta=0.1)

    def test_same_direction_after_stop_needs_no_take_up(self):
        self.mount.move("az", 1, 1)
        self.wait_rate(16, 1)
        self.mount.drive(0, 0)
        time.sleep(0.05)
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 1)

    def test_stop_during_take_up_remembers_the_rest(self):
        self.mount.move("az", 1, 1)
        self.wait_rate(16, 1)
        self.mount.move("az", -1, 1)
        time.sleep(0.08)
        self.mount.drive(0, 0)
        time.sleep(0.05)
        rest = self.mount.gap["az"]
        self.assertGreater(rest, 0.05)
        self.assertLess(rest, 0.55)
        start = time.monotonic()
        self.mount.move("az", -1, 1)
        self.assertEqual(self.fake.rates[16], -6)
        self.wait_rate(16, -1)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_time_source_uses_the_speed_table(self):
        self.mount.move("alt", 1, 1)
        self.wait_rate(17, 1)
        start = time.monotonic()
        self.mount.move("alt", -1, 1)
        self.assertEqual(self.fake.rates[17], -6)
        self.wait_rate(17, -1)
        # 0.3° を表の 3°/s で詰めるので約 0.1 秒
        self.assertAlmostEqual(time.monotonic() - start, 0.1, delta=0.08)

    def test_tracking_takes_up_the_gap_first(self):
        self.mount.move("az", -1, 1)
        self.wait_rate(16, -1)
        self.mount.drive(0, 0)
        self.mount.track({"az": 15.0})
        self.assertEqual(self.fake.rates[16], 6)
        self.wait_rate(16, 15.0)
        self.assertEqual(self.mount.status()["moving"], {})

    def test_fast_request_is_not_changed(self):
        self.mount.move("az", 1, 6)
        self.assertEqual(self.fake.rates[16], 6)
        self.assertEqual(self.mount.status()["moving"]["az"]["actual"], 6)

    def test_heartbeat_during_take_up_keeps_the_fast_rate(self):
        self.mount.move("az", 1, 1)
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 6)


class SafetyTest(unittest.TestCase):
    """2026-11-07 の暴走の再発防止。裏返り、飛び、高度の時間積算、1 回の操作の上限。"""

    def make(self, alt_start=0.0, **kwargs):
        self.fake = FakeSynScan()
        self.fake.flip_reporting = True
        self.fake.position[17] = alt_start
        self.fake.start()
        options = dict(az_limit=180.0, alt_limit=90.0, hold_timeout=0.4, poll_interval=0.02,
                       alt_start_delay=0.0)
        options.update(kwargs)
        self.mount = Mount(self.fake.port, max_rate=9, **options)
        self.addCleanup(self.mount.close)

    def hold(self, axis, direction, rate, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.mount.move(axis, direction, rate)
            time.sleep(0.05)

    def test_flip_at_90_degrees_is_undone(self):
        self.make(alt_start=88.0)
        self.fake.speed = 4.0
        self.hold("alt", 1, 1, 1.0)
        self.mount.drive(0, 0)
        time.sleep(0.1)
        status = self.mount.status()
        self.assertTrue(status["flipped"])
        self.assertFalse(status["jumped"])
        self.assertAlmostEqual(status["raw"]["az"] % 360, 0.0, delta=0.5)
        self.assertGreater(status["raw"]["alt"], 90.0)
        self.assertAlmostEqual(status["alt_read"], self.fake.position[17] - 88.0, delta=0.5)

    def test_flip_state_is_carried_over_when_the_mount_has_not_moved(self):
        # 高度 100° は、裏返った表し方では「方位 +180°、高度 80°」で返る
        self.make(alt_start=100.0, flip_hint={"flipped": True, "reported": {"az": 180.0, "alt": 80.0}})
        status = self.mount.status()
        self.assertTrue(status["flipped"])
        self.assertAlmostEqual(status["raw"]["az"], 0.0, delta=0.01)
        self.assertAlmostEqual(status["raw"]["alt"], 100.0, delta=0.01)

    def test_flip_state_is_not_carried_over_after_a_move(self):
        self.make(alt_start=100.0, flip_hint={"flipped": True, "reported": {"az": 180.0, "alt": 70.0}})
        self.assertFalse(self.mount.status()["flipped"])

    def test_flip_far_from_the_pole_is_a_jump(self):
        self.make()
        self.mount.move("az", 1, 1)
        self.fake.position[16] += 180.0
        time.sleep(0.15)
        status = self.mount.status()
        self.assertTrue(status["jumped"])
        self.assertEqual(status["moving"], {})
        self.assertEqual(self.fake.rates, {16: 0, 17: 0})
        self.assertIn("飛んだ", status["message"])

    def test_jump_keeps_the_axis_stopped_until_release(self):
        self.make()
        self.mount.move("az", 1, 1)
        self.fake.position[16] += 30.0
        time.sleep(0.15)
        with self.assertRaises(MountError):
            self.mount.move("az", 1, 1)
        self.mount.move("az", -1, 1)  # 逆向きには動かせる
        self.mount.drive(0, 0)
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 1)

    def test_altitude_position_uses_speed_and_time(self):
        self.make(speeds={1: 2.0})
        self.hold("alt", 1, 1, 0.5)
        self.mount.drive(0, 0)
        status = self.mount.status()
        self.assertAlmostEqual(status["alt"], 1.0, delta=0.25)
        self.assertAlmostEqual(status["alt_read"], 0.0, delta=0.01)  # 架台の読み取りは動いていない

    def test_altitude_limit_uses_speed_and_time(self):
        self.make(speeds={1: 2.0}, alt_limit=0.5)
        self.hold("alt", 1, 1, 0.3)
        with self.assertRaises(MountError):
            self.hold("alt", 1, 1, 0.5)
        self.assertEqual(self.fake.rates[17], 0)

    def test_stroke_stops_at_the_angle_cap(self):
        self.make(speeds={1: 2.0}, max_move_deg=0.5)
        with self.assertRaises(MountError):
            self.hold("az", 1, 1, 1.0)
        self.assertEqual(self.fake.rates[16], 0)
        self.assertIn("上限", self.mount.status()["message"])
        self.mount.drive(0, 0)
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 1)

    def test_rate_change_does_not_reset_the_stroke(self):
        self.make(speeds={1: 2.0, 2: 2.0}, max_move_deg=0.5)
        with self.assertRaises(MountError):
            for rate in (1, 2) * 10:
                self.hold("az", 1, rate, 0.1)

    def test_stroke_stops_at_the_time_cap(self):
        self.make(max_move_seconds=0.3)
        with self.assertRaises(MountError):
            self.hold("alt", -1, 1, 1.0)
        self.assertEqual(self.fake.rates[17], 0)

    def test_released_after_hold_timeout(self):
        self.make(max_move_seconds=0.2)
        with self.assertRaises(MountError):
            self.hold("az", 1, 1, 1.0)
        time.sleep(0.5)  # 命令が途切れたら、離したものとみなす
        self.mount.move("az", 1, 1)
        self.assertEqual(self.fake.rates[16], 1)


class GotoTest(unittest.TestCase):
    """SynScan の自動導入（r）の監視。計画を外れたら M と停止を送る。"""

    def setUp(self):
        self.fake = FakeSynScan()
        self.fake.aligned = 1
        self.fake.position = {16: 100.0, 17: 30.0}
        self.fake.start()
        self.mount = Mount(self.fake.port, az_limit=180.0, alt_limit=90.0, hold_timeout=0.4, poll_interval=0.05)

    def tearDown(self):
        self.mount.close()

    def plan(self, **values):
        plan = {"label": "M1", "az_direction": -1, "az_amount": 12.0, "alt_range": [20.0, 40.0], "timeout": 5.0}
        plan.update(values)
        return plan

    def wait_done(self, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and self.mount.status()["goto"]:
            time.sleep(0.05)

    def test_sends_ra_and_dec_and_reports_completion(self):
        self.fake.goto_velocity = {16: -12.0, 17: -5.0}
        self.fake.goto_seconds = 1.0
        self.fake.tracking_mode = 1  # アライメント済みの SynScan は導入の後に追尾する
        self.mount.start_goto(5.575538888888889, 22.0145, self.plan())
        self.assertEqual(self.fake.goto_commands, ["3B78F000,0FA79E00"])
        self.assertTrue(self.mount.status()["goto"])
        self.wait_done()
        status = self.mount.status()
        self.assertIsNone(status["goto"])
        self.assertTrue(status["goto_result"]["ok"])
        self.assertEqual(self.fake.cancels, 0)
        self.assertTrue(status["synscan_tracking"])
        # 自動導入の間の高度は読み取りで進める
        self.assertAlmostEqual(status["alt"], -5.0, delta=0.5)

    def test_brief_idle_report_at_the_start_is_not_completion(self):
        # 実機では小さな移動の始めに L が一瞬 0 を返した。動いている間は終わりとみなさない
        self.fake.goto_velocity = {16: 0.0, 17: 1.0}
        self.fake.goto_seconds = 2.5
        self.fake.goto_idle_until = 1.5  # 始めの 1.5 秒は動いていても L が 0
        self.mount.start_goto(5.5, 22.0, self.plan(az_amount=1.0, alt_range=[20.0, 40.0]))
        time.sleep(2.0)
        self.assertTrue(self.mount.status()["goto"])
        self.wait_done()
        self.assertTrue(self.mount.status()["goto_result"]["ok"])
        self.assertAlmostEqual(self.mount.status()["raw"]["alt"], 32.5, delta=0.3)

    def test_negative_declination_is_twos_complement(self):
        self.fake.goto_seconds = 0.0
        self.mount.start_goto(5.588, -5.3911, self.plan(az_amount=1.0))
        dec = int(self.fake.goto_commands[0].split(",")[1], 16)
        self.assertAlmostEqual(dec / 2 ** 32 * 360 - 360, -5.3911, places=4)

    def test_wrong_direction_cancels(self):
        self.fake.goto_velocity = {16: 20.0, 17: 0.0}
        self.fake.goto_seconds = 3.0
        self.mount.start_goto(5.5, 22.0, self.plan())
        self.wait_done()
        status = self.mount.status()
        self.assertFalse(status["goto_result"]["ok"])
        self.assertIn("逆向き", status["goto_result"]["message"])
        self.assertEqual(self.fake.cancels, 1)

    def test_overshoot_cancels(self):
        self.fake.goto_velocity = {16: -40.0, 17: 0.0}
        self.fake.goto_seconds = 3.0
        self.mount.start_goto(5.5, 22.0, self.plan())
        self.wait_done()
        self.assertIn("多く", self.mount.status()["goto_result"]["message"])
        self.assertEqual(self.fake.cancels, 1)

    def test_altitude_out_of_range_cancels(self):
        self.fake.goto_velocity = {16: 0.0, 17: 20.0}
        self.fake.goto_seconds = 3.0
        self.mount.start_goto(5.5, 22.0, self.plan())
        self.wait_done()
        self.assertIn("高度", self.mount.status()["goto_result"]["message"])
        self.assertEqual(self.fake.cancels, 1)

    def test_timeout_cancels(self):
        self.fake.goto_seconds = 10.0
        self.mount.start_goto(5.5, 22.0, self.plan(timeout=0.5))
        self.wait_done()
        self.assertIn("時間", self.mount.status()["goto_result"]["message"])
        self.assertEqual(self.fake.cancels, 1)

    def test_stop_cancels_the_goto(self):
        self.fake.goto_seconds = 10.0
        self.mount.start_goto(5.5, 22.0, self.plan(timeout=20.0))
        self.mount.stop()
        self.assertEqual(self.fake.cancels, 1)
        self.assertIsNone(self.mount.status()["goto"])
        self.assertFalse(self.mount.status()["goto_result"]["ok"])

    def test_stick_and_tracking_are_refused_during_goto(self):
        self.fake.goto_seconds = 10.0
        self.mount.start_goto(5.5, 22.0, self.plan(timeout=20.0))
        with self.assertRaises(MountError):
            self.mount.move("az", 1, 3)
        with self.assertRaises(MountError):
            self.mount.track({"az": 1.0, "alt": 1.0})
        self.mount.stop()

    def test_refused_without_synscan_alignment(self):
        self.fake.aligned = 0
        with self.assertRaises(MountError):
            self.mount.start_goto(5.5, 22.0, self.plan())
        self.assertEqual(self.fake.goto_commands, [])

    def test_tracking_mode_commands(self):
        self.assertEqual(self.mount.tracking_mode(), "off")
        self.mount.set_tracking_mode("altaz")
        self.assertEqual(self.fake.tracking_commands, [1])
        self.assertEqual(self.mount.tracking_mode(), "altaz")
        self.mount.set_tracking_mode("off")
        self.assertEqual(self.fake.tracking_commands, [1, 0])

    def test_synscan_tracking_is_refused_while_the_server_tracks(self):
        self.mount.track({"az": 5.0, "alt": 5.0})
        with self.assertRaises(MountError):
            self.mount.set_tracking_mode("altaz")
        self.mount.set_tracking_mode("off")  # 切るのはいつでもできる

    def test_stick_marks_synscan_tracking_as_cancelled(self):
        self.fake.tracking_mode = 1
        self.mount.tracking_mode()
        self.mount.move("az", 1, 3)
        self.assertFalse(self.mount.status()["synscan_tracking"])
        self.mount.stop()


if __name__ == "__main__":
    unittest.main()
