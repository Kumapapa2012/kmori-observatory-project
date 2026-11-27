#!/usr/bin/env python3
"""フォーカスドライバーの操作を、疑似のシリアルで確かめる。実機には接続しない。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.focuser import Focuser, FocuserError


class FakePico:
    def __init__(self, replies=None, broken=False):
        self.sent = []
        self.replies = replies
        self.broken = broken
        self.lines = []

    def reset_input_buffer(self):
        self.lines = []

    def write(self, data):
        if self.broken:
            raise OSError("unplugged")
        self.sent.append(data.decode().strip())
        self.lines = list(self.replies if self.replies is not None else [b"DONE\n", b"OK\n"])

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        pass


class FocuserTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.port = Path(tmp.name) / "usb-MicroPython-test"
        self.cfg = {"port_glob": str(Path(tmp.name) / "*MicroPython*")}

    def focuser(self, *links):
        links = list(links)
        return Focuser(self.cfg, open_port=lambda port: links.pop(0))

    def test_not_set(self):
        focuser = self.focuser()
        self.assertFalse(focuser.status()["connected"])
        with self.assertRaisesRegex(FocuserError, "セットしてください"):
            focuser.move(1, "fine")

    def test_move_and_stop(self):
        self.port.touch()
        pico = FakePico()
        focuser = self.focuser(pico)
        focuser.move(1, "fine")
        focuser.move(-1, "fast")
        focuser.stop()
        self.assertEqual(pico.sent, ["M 6", "M -60", "X"])

    def test_rejects_unknown_values(self):
        self.port.touch()
        for args in ((0, "fine"), (2, "fine"), (1, "turbo")):
            with self.assertRaises(ValueError):
                self.focuser().move(*args)

    def test_reopens_after_replug(self):
        self.port.touch()
        new = FakePico()
        self.focuser(FakePico(broken=True), new).move(1, "mid")
        self.assertEqual(new.sent, ["M 15"])

    def test_no_reply(self):
        self.port.touch()
        with self.assertRaisesRegex(FocuserError, "応答"):
            self.focuser(FakePico(replies=[])).move(1, "mid")


if __name__ == "__main__":
    unittest.main()
