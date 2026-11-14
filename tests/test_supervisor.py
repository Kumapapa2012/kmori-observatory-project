#!/usr/bin/env python3
"""架台の接続の切り替え（MountSupervisor.set_enabled）を疑似シリアルで確かめる。実機には接続しない。"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from observatory.app import MountSupervisor
from test_mount import FakeSynScan


def wait_until(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


class SupervisorTest(unittest.TestCase):
    def make(self, enabled=True):
        self.fake = FakeSynScan()
        self.fake.start()
        self.connected = []
        cfg = {"port": self.fake.port, "max_rate": 9, "az_limit": 180.0, "alt_limit": 90.0}
        self.supervisor = MountSupervisor(cfg, on_connect=lambda m: self.connected.append(m.synscan_aligned()),
                                          enabled=enabled)
        self.supervisor.start()
        self.addCleanup(self.supervisor.close)

    def test_connects_and_reports_synscan_alignment(self):
        self.make()
        self.assertTrue(wait_until(lambda: self.supervisor.mount is not None))
        self.assertTrue(wait_until(lambda: self.connected == [False]))

    def test_disconnect_stops_the_mount_and_releases_the_port(self):
        self.make()
        self.assertTrue(wait_until(lambda: self.supervisor.mount is not None))
        mount = self.supervisor.mount
        mount.move("az", 1, 3)
        self.assertEqual(self.fake.rates[16], 3)
        self.supervisor.set_enabled(False)
        self.assertIsNone(self.supervisor.mount)
        self.assertEqual(self.fake.rates, {16: 0, 17: 0})
        self.assertFalse(mount.serial.is_open)
        time.sleep(0.5)
        self.assertIsNone(self.supervisor.mount)  # 切断中は接続し直さない

    def test_disabled_at_start_never_connects(self):
        self.make(enabled=False)
        time.sleep(0.5)
        self.assertIsNone(self.supervisor.mount)
        self.assertEqual(self.connected, [])

    def test_reconnect_is_immediate(self):
        self.make(enabled=False)
        self.fake.aligned = 1
        start = time.monotonic()
        self.supervisor.set_enabled(True)
        self.assertTrue(wait_until(lambda: self.supervisor.mount is not None, timeout=2.0))
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertTrue(wait_until(lambda: self.connected == [True]))


if __name__ == "__main__":
    unittest.main()
