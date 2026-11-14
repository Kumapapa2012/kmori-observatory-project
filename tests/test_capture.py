#!/usr/bin/env python3
"""撮影の状態遷移を、FFmpeg とカメラの代役で確かめる。"""
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.capture import Capture, CaptureError, Commands, JpegSplitter, clean_target, night_folder
from observatory.state import StateStore

CFG = {"rtsp_url": "rtsp://127.0.0.1:8554/camera", "render_device": "/dev/dri/renderD128", "min_free_gb": 10,
       "video_mb_per_second": 125, "video_default_seconds": 120, "video_max_seconds": 900,
       "timelapse_min_interval": 5, "stall_seconds": 10, "settle_seconds": 1, "still_timeout": 15, "stop_timeout": 5}


class FakeProc:
    def __init__(self, command):
        self.command = command
        self.code = None
        self.signals = []
        self.stdout = SimpleNamespace(read1=lambda n: b"")

    def poll(self):
        return self.code

    def send_signal(self, value):
        self.signals.append(value)
        self.code = 0

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.now = 1_800_000_000.0
        self.free = 100e9
        self.procs = []
        self.fake_commands = []
        self.controls = {"manual": True, "exposure": 100, "gain": 20}
        self.reasserts = 0
        self.store = StateStore(base / "state.json")
        self.capture = self.make(base)

    def make(self, base):
        return Capture(CFG, "/dev/video0", self.store,
                       SimpleNamespace(controls=lambda: self.controls, reassert=self.fake_reassert),
                       lambda: {"az": 1.0, "alt": 2.0}, base / "captures", base / "preview",
                       popen=self.popen, run=self.fake_run, free_bytes=lambda: self.free, clock=lambda: self.now,
                       sleep=lambda seconds: None)

    def fake_reassert(self):
        self.reasserts += 1
        return True

    def wait_reasserts(self, count):
        end = time.monotonic() + 2
        while self.reasserts < count and time.monotonic() < end:
            time.sleep(0.01)
        return self.reasserts

    def tearDown(self):
        self.dir.cleanup()

    def popen(self, command, **kwargs):
        self.procs.append(FakeProc(command))
        return self.procs[-1]

    def fake_run(self, command, **kwargs):
        self.fake_commands.append(command)
        Path(command[-1]).write_bytes(b"image")
        return SimpleNamespace(returncode=0, stderr="")

    def rec(self):
        return self.store.get()["recording"]

    def test_still_saves_file_and_returns_to_live(self):
        path = self.capture.still("moon")
        self.assertTrue((self.capture.root / path / "still.png").exists())
        self.assertIn("moon", path)
        self.assertEqual(self.rec()["kind"], "none")
        self.assertEqual(self.rec()["count"], 1)
        self.assertIn("1920x1080", self.procs[-1].command)

    def test_still_failure_is_reported_and_live_returns(self):
        self.capture.run = lambda *a, **k: SimpleNamespace(returncode=1, stderr="busy")
        with self.assertRaises(CaptureError):
            self.capture.still()
        self.assertEqual(self.rec()["state"], "error")
        self.assertIn("1920x1080", self.procs[-1].command)

    def test_still_waits_for_the_exposure_reassert(self):
        self.capture.still()
        # 静止画の取得と、そのあとのライブの再開で、それぞれ 2 回ずつかけ直す
        self.assertGreaterEqual(self.wait_reasserts(4), 4)
        still = next(p for p in self.fake_commands if "3264x2160" in p)
        self.assertIn("select=gte(t\\,3.02)", still)

    def test_video_discards_until_the_exposure_reassert(self):
        self.controls = {"manual": True, "exposure": 5000, "gain": 20}
        self.capture.video(10)
        command = self.procs[-1].command
        self.assertEqual(command[command.index("-ss") + 1], "4.00")
        self.assertGreaterEqual(self.wait_reasserts(2), 2)

    def test_only_one_recording_at_a_time(self):
        self.capture.timelapse(5)
        for start in (self.capture.still, lambda: self.capture.video(10), lambda: self.capture.timelapse(5)):
            with self.assertRaises(CaptureError):
                start()

    def test_timelapse_rejects_short_interval(self):
        with self.assertRaises(CaptureError) as e:
            self.capture.timelapse(4.9)
        self.assertEqual(e.exception.status, 400)

    def test_recording_requires_manual_exposure(self):
        self.controls = {"manual": False, "exposure": 100, "gain": 20}
        for start in (lambda: self.capture.timelapse(5), lambda: self.capture.video(5)):
            with self.assertRaises(CaptureError):
                start()
        self.assertEqual(self.rec()["kind"], "none")

    def test_timelapse_saves_on_schedule(self):
        self.capture.timelapse(5)
        session = self.capture.session
        chunks = iter([b"\xff\xd8\xffA\xff\xd8\xffB\xff\xd8\xff", b""])
        proc = SimpleNamespace(stdout=SimpleNamespace(read1=lambda n: next(chunks)))
        self.capture._read_frames(proc, session)
        self.assertEqual(session["count"], 0)  # カメラが落ち着くまで保存しない
        self.now += 1
        chunks = iter([b"\xff\xd8\xffA\xff\xd8\xffB\xff\xd8\xff", b""])
        self.capture._read_frames(proc, session)
        self.assertEqual(session["count"], 0)  # 露出のかけ直しが効くまで（3 秒 + 露出の 2 倍）も保存しない
        self.now += 2.1
        chunks = iter([b"\xff\xd8\xffA\xff\xd8\xffB\xff\xd8\xff", b""])
        self.capture._read_frames(proc, session)
        self.assertEqual(session["count"], 1)  # 間隔の前の次のフレームは保存しない
        self.assertEqual((session["folder"] / "frame_00001.jpg").read_bytes(), b"\xff\xd8\xffA")
        self.assertEqual(self.rec()["count"], 1)

    def test_timelapse_restarts_ffmpeg_and_continues(self):
        self.capture.timelapse(5)
        self.procs[-1].code = 1
        count = len(self.procs)
        self.capture.tick()
        self.assertEqual(len(self.procs), count + 1)
        self.assertEqual(self.rec()["kind"], "timelapse")
        self.assertIn("restart", (self.capture.session["folder"] / "metadata.jsonl").read_text())

    def test_timelapse_restarts_when_frames_stop(self):
        self.capture.timelapse(5)
        count = len(self.procs)
        self.now += 11
        self.capture.tick()
        self.assertEqual(len(self.procs), count + 1)

    def test_video_stops_at_duration_and_renames(self):
        path = self.capture.video(10)
        part = self.capture.session["part"]
        part.write_bytes(b"x")
        self.now += 10
        self.capture.tick()
        # 露出のかけ直しを待つ 3.02 秒（3 秒 + 露出 0.01 秒の 2 倍）の分だけ長く回す
        self.assertEqual(self.rec()["kind"], "video")
        self.now += 3.02
        self.capture.tick()
        self.assertEqual(self.rec()["kind"], "none")
        self.assertEqual(self.rec()["state"], "idle")
        self.assertTrue((self.capture.root / path / "video.avi").exists())
        self.assertFalse(part.exists())
        self.assertIn("1920x1080", self.procs[-1].command)

    def test_video_process_death_is_an_error(self):
        self.capture.video(10)
        self.procs[-1].code = 1
        self.capture.tick()
        self.assertEqual(self.rec()["state"], "error")

    def test_video_stops_when_file_stops_growing(self):
        self.capture.video(100)
        self.now += 11
        self.capture.tick()
        self.assertEqual(self.rec()["state"], "error")

    def test_video_refused_without_room(self):
        self.free = 10e9 + 100e6
        with self.assertRaises(CaptureError):
            self.capture.video(10)

    def test_low_disk_stops_recording(self):
        self.capture.timelapse(5)
        self.free = 9e9
        self.capture.tick()
        self.assertEqual(self.rec()["state"], "error")
        self.assertIn("空き容量", self.rec()["message"])

    def test_stop_uses_sigint_so_file_closes(self):
        self.capture.video(10)
        proc = self.procs[-1]
        self.capture.stop()
        self.assertEqual(proc.signals, [signal.SIGINT])

    def test_stop_without_recording(self):
        with self.assertRaises(CaptureError):
            self.capture.stop()

    def test_recover_marks_interrupted_and_keeps_file(self):
        path = self.capture.video(10)
        part = self.capture.session["part"]
        part.write_bytes(b"x")
        fresh = self.make(Path(self.dir.name))
        fresh.recover()
        self.assertEqual(self.rec()["state"], "interrupted")
        self.assertEqual(self.rec()["kind"], "none")
        self.assertTrue((fresh.root / path / "video.avi").exists())

    def test_close_does_not_restart_live(self):
        self.capture.timelapse(5)
        count = len(self.procs)
        self.capture.close()
        self.assertEqual(len(self.procs), count)
        self.assertEqual(self.rec()["state"], "interrupted")

    def test_live_restarts_after_failure(self):
        self.capture.tick()
        self.assertEqual(len(self.procs), 1)
        self.procs[-1].code = 1
        self.now += 4
        self.capture.tick()
        self.assertEqual(len(self.procs), 2)
        self.assertEqual(self.capture.epoch, 2)

    def test_list_sessions_skips_hidden_and_metadata(self):
        self.capture.still("moon")
        (self.capture.root / ".bench" / "x").mkdir(parents=True)
        sessions = self.capture.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["files"], 1)
        self.assertEqual(sessions[0]["latest"], "still.png")


class HelperTest(unittest.TestCase):
    def test_splitter_handles_marker_across_reads(self):
        splitter = JpegSplitter()
        self.assertEqual(splitter.feed(b"junk\xff\xd8\xffA\xff"), [])
        self.assertEqual(splitter.feed(b"\xd8\xffB\xff\xd8"), [b"\xff\xd8\xffA"])
        self.assertEqual(splitter.feed(b"\xff"), [b"\xff\xd8\xffB"])

    def test_night_folder_counts_early_morning_as_previous_night(self):
        self.assertEqual(night_folder(datetime(2026, 11, 2, 3)), "2026-11-01")
        self.assertEqual(night_folder(datetime(2026, 11, 2, 13)), "2026-11-02")

    def test_clean_target_blocks_path(self):
        self.assertEqual(clean_target("../木星 a/b"), "木星ab")
        self.assertEqual(clean_target(None), "")

    def test_commands(self):
        c = Commands(CFG, "/dev/video0")
        self.assertIn("pipe:1", c.timelapse())
        self.assertIn("yuyv422", c.video("v.avi", 3.0))
        self.assertEqual(c.still("s.png", 3.0)[-1], "s.png")


if __name__ == "__main__":
    unittest.main()
