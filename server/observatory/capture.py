"""ライブ配信と撮影の FFmpeg を管理する。カメラを開けるのは 1 プロセスだけなので、1 つの FFmpeg から両方を出す。"""
import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

SOI = b"\xff\xd8\xff"
TICK_INTERVAL = 0.5
LIVE_RETRY_INTERVAL = 3.0
PREVIEW_HEIGHT = 1080
# カメラを開いた直後のフレームは使わない。自動露出は明るさが落ち着くまで長く待つ
# 配信の開始のあと、手動露出をかけ直す時刻（秒）。開始直後は効かないことがあるので 2 回かける
REASSERT_DELAYS = (1.0, 2.5)
# かけ直しが効いたあとの映像だけを使うまでの時間。これに露出時間の 2 倍を足す
REASSERT_SETTLE = 3.0
VIDEO_PART, VIDEO_FILE = "video.part.avi", "video.avi"


def settle_seconds(controls):
    """露出のかけ直しが効いた映像になるまでの秒数。手動露出なら露出時間の 2 倍を足す。"""
    exposure = controls["exposure"] / 10000 if controls and controls.get("manual") else 0.0
    return REASSERT_SETTLE + 2 * exposure


class CaptureError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class JpegSplitter:
    """MJPEG のバイト列をフレームに分ける。カメラは終端を省くことがあるので、次の開始で区切る。"""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer += data
        frames = []
        while True:
            start = self.buffer.find(SOI)
            if start < 0:
                # 開始の印が 2 回の読み取りにまたがる場合に備えて末尾を残す
                del self.buffer[:-2]
                return frames
            end = self.buffer.find(SOI, start + 1)
            if end < 0:
                del self.buffer[:start]
                return frames
            frames.append(bytes(self.buffer[start:end]))
            del self.buffer[:end]


def night_folder(now):
    """正午より前は前日の観測夜に含める。"""
    return (now - timedelta(hours=12)).strftime("%Y-%m-%d")


def clean_target(target):
    return re.sub(r"[^\w-]", "", str(target or ""))[:40]


class Commands:
    """FFmpeg の引数を組み立てる。"""

    def __init__(self, cfg, device):
        self.device = device
        self.rtsp_url = cfg["rtsp_url"]
        self.render = cfg["render_device"]

    def _base(self):
        return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning"]

    def _hw(self):
        # デコードとエンコードの両方を GPU で行う
        return ["-hwaccel", "vaapi", "-hwaccel_device", self.render, "-hwaccel_output_format", "vaapi"]

    def _input(self, fmt, size):
        return ["-fflags", "nobuffer", "-flags", "low_delay",
                "-f", "v4l2", "-input_format", fmt, "-video_size", size, "-i", self.device]

    def _live(self, video_filter):
        # ブラウザとの相性と遅延のため、Baseline で B フレームなし、キーフレームは 1 秒ごと
        return ["-map", "0:v", "-vf", video_filter,
                "-c:v", "h264_vaapi", "-profile:v", "constrained_baseline", "-bf", "0", "-g", "30",
                "-rc_mode", "VBR", "-b:v", "8M", "-maxrate", "12M", "-async_depth", "1",
                "-f", "rtsp", "-rtsp_transport", "tcp", "-pkt_size", "1200", self.rtsp_url]

    def live(self):
        return (self._base() + self._hw() + self._input("mjpeg", "1920x1080")
                + self._live("scale_vaapi=format=nv12"))

    def timelapse(self):
        return (self._base() + self._hw() + self._input("mjpeg", "3264x2160")
                + ["-map", "0:v", "-c:v", "copy", "-f", "mjpeg", "pipe:1"]
                + self._live("scale_vaapi=w=1632:h=1080:format=nv12"))

    def video(self, path, discard_seconds):
        return (self._base() + ["-vaapi_device", self.render] + self._input("yuyv422", "1920x1080")
                + ["-map", "0:v", "-ss", f"{discard_seconds:.2f}", "-c:v", "rawvideo", "-f", "avi", str(path)]
                + self._live("format=nv12,hwupload"))

    def still(self, path, settle_seconds):
        # 露出のかけ直しが効いたあとの最初のフレームを使う。t は最初のフレームからの秒
        return (self._base() + ["-y"] + self._input("yuyv422", "3264x2160")
                + ["-vf", f"select=gte(t\\,{settle_seconds:.2f})", "-frames:v", "1", "-update", "1", str(path)])

    def preview(self, source, path):
        return self._base() + ["-y", "-i", str(source), "-vf", f"scale=-2:{PREVIEW_HEIGHT}", "-q:v", "3", str(path)]


class Capture:
    def __init__(self, cfg, device, store, camera, mount_raw, root, preview_dir,
                 popen=subprocess.Popen, run=subprocess.run, free_bytes=None, clock=time.time, sleep=time.sleep):
        self.cfg = cfg
        self.commands = Commands(cfg, device)
        self.store = store
        self.camera = camera
        self.mount_raw = mount_raw
        self.root = Path(root)
        self.preview_dir = Path(preview_dir)
        self.popen = popen
        self.run = run
        self.free_bytes = free_bytes or (lambda: shutil.disk_usage(self.root).free)
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.RLock()
        self.closing = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.proc = None
        self.session = None
        self.epoch = 0
        self.preview_seq = 0
        self.preview_busy = threading.Lock()
        self.next_live_try = 0.0
        self.root.mkdir(parents=True, exist_ok=True)

    # 外から呼ぶ操作
    def start(self):
        self.recover()
        with self.lock:
            self._start_live()
        self.thread.start()

    def close(self):
        self.closing.set()
        with self.lock:
            if self.session:
                self._finish("interrupted", "サーバーの終了で撮影を止めました")
            self._stop_proc()

    def status(self):
        """切断から戻った端末も、ここから録画中かどうかを知る。"""
        try:
            free = self.free_bytes() / 1e9
        except OSError:
            free = None
        return {**self.store.get()["recording"], "free_gb": free,
                "preview_seq": self.preview_seq, "stream_epoch": self.epoch}

    def locks_exposure(self):
        return self.store.get()["recording"]["kind"] in ("timelapse", "video")

    def recover(self):
        """前回のサーバーが撮影の途中で落ちたときの後始末。ファイルは消さない。"""
        rec = self.store.get()["recording"]
        if rec.get("kind", "none") == "none":
            return
        if rec.get("kind") == "video" and rec.get("path"):
            part = self.root / rec["path"] / VIDEO_PART
            if part.exists():
                os.replace(part, part.with_name(VIDEO_FILE))
        self.store.update(recording={
            "kind": "none", "state": "interrupted", "last_kind": rec.get("kind"), "path": rec.get("path"),
            "count": rec.get("count", 0), "message": "サーバーの再起動で撮影が途切れました"})

    def still(self, target=None):
        with self.lock:
            self._require_idle()
            self._require_free(0)
            controls = self._controls()
            folder = self._new_folder("still", target)
            self._set_recording("still", "recording", folder, count=0)
            self._stop_proc()
            part, path = folder / "still.part.png", folder / "still.png"
            try:
                self._reassert_later()
                result = self.run(self.commands.still(part, settle_seconds(controls)),
                                  timeout=self.cfg["still_timeout"], capture_output=True, text=True)
                if result.returncode != 0 or not part.exists():
                    raise CaptureError(f"静止画を取得できません: {result.stderr.strip()[-200:]}", 503)
                os.replace(part, path)
                self._metadata(folder, file=path.name, controls=controls)
                self._make_preview(path)
            except (CaptureError, OSError, subprocess.SubprocessError) as e:
                self._set_idle("error", "still", folder, 0, str(e))
                raise CaptureError(str(e), 503) from e
            finally:
                self._start_live()
            self._set_idle("idle", "still", folder, 1, "")
            return self._relative(folder)

    def timelapse(self, interval, target=None):
        interval = self._number(interval, "間隔")
        if interval < self.cfg["timelapse_min_interval"]:
            raise CaptureError(f"間隔は {self.cfg['timelapse_min_interval']} 秒以上にしてください", 400)
        with self.lock:
            self._require_idle()
            self._require_free(0)
            controls = self._require_manual()
            folder = self._new_folder("timelapse", target)
            self.session = {"kind": "timelapse", "folder": folder, "interval": interval, "count": 0,
                            "controls": controls, "next_shot": 0.0}
            self._set_recording("timelapse", "recording", folder, count=0, interval=interval)
            self._stop_proc()
            self._spawn_timelapse()
            return self._relative(folder)

    def video(self, seconds=None, target=None):
        seconds = self._number(seconds if seconds is not None else self.cfg["video_default_seconds"], "長さ")
        if not 1 <= seconds <= self.cfg["video_max_seconds"]:
            raise CaptureError(f"長さは 1〜{self.cfg['video_max_seconds']} 秒にしてください", 400)
        with self.lock:
            self._require_idle()
            self._require_free(seconds * self.cfg["video_mb_per_second"] * 1e6)
            controls = self._require_manual()
            folder = self._new_folder("video", target)
            part = folder / VIDEO_PART
            # 露出のかけ直しを待つ間は記録しないので、その分だけ長く回して指定の長さを残す
            discard = settle_seconds(controls)
            self.session = {"kind": "video", "folder": folder, "part": part, "ends_at": self.clock() + seconds + discard,
                            "last_size": 0, "last_growth": self.clock(), "count": 0}
            self._set_recording("video", "recording", folder, count=0, seconds=seconds)
            self._metadata(folder, event="start", controls=controls)
            self._stop_proc()
            self._spawn(self.commands.video(part, discard))
            return self._relative(folder)

    def stop(self):
        with self.lock:
            if not self.session:
                raise CaptureError("撮影していません")
            self._finish("idle", "")

    def list_sessions(self, limit=30):
        sessions = []
        folders = [p for night in self.root.iterdir() if night.is_dir() and not night.name.startswith(".")
                   for p in night.iterdir() if p.is_dir()]
        for folder in sorted(folders, key=lambda p: (p.parent.name, p.name), reverse=True)[:limit]:
            files = sorted(f for f in folder.iterdir() if f.is_file() and f.name != "metadata.jsonl")
            sessions.append({"path": self._relative(folder), "files": len(files),
                             "size": sum(f.stat().st_size for f in files),
                             "latest": files[-1].name if files else None})
        return sessions

    # 監視
    def _loop(self):
        while not self.closing.wait(TICK_INTERVAL):
            try:
                self.tick()
            except Exception as e:
                # 監視が止まると録画の上限や空き容量を見られなくなる
                print(f"capture monitor error: {e}", flush=True)

    def tick(self):
        with self.lock:
            if self.closing.is_set():
                return
            session = self.session
            if session is None:
                if (self.proc is None or self.proc.poll() is not None) and self.clock() >= self.next_live_try:
                    self.next_live_try = self.clock() + LIVE_RETRY_INTERVAL
                    self._start_live()
                return
            if self.free_bytes() < self.cfg["min_free_gb"] * 1e9:
                self._finish("error", "空き容量が少ないので撮影を止めました")
            elif session["kind"] == "timelapse":
                self._tick_timelapse(session)
            else:
                self._tick_video(session)

    def _tick_timelapse(self, session):
        stalled = self.clock() - session["last_frame"] > self.cfg["stall_seconds"]
        if self.proc.poll() is None and not stalled:
            return
        # 撮影は続ける。欠けた時間を後から追えるように記録を残す
        print("timelapse: restarting ffmpeg", flush=True)
        self._metadata(session["folder"], event="restart", last_frame=session["last_frame"])
        self._stop_proc()
        self._spawn_timelapse()

    def _tick_video(self, session):
        now = self.clock()
        if self.proc.poll() is not None:
            self._finish("error", "記録が途中で止まりました")
        elif now >= session["ends_at"]:
            self._finish("idle", "")
        else:
            size = session["part"].stat().st_size if session["part"].exists() else 0
            if size > session["last_size"]:
                session["last_size"], session["last_growth"] = size, now
            elif now - session["last_growth"] > self.cfg["stall_seconds"]:
                self._finish("error", "記録が進まないので止めました")

    # 内部の処理
    def _require_idle(self):
        if self.session or self.store.get()["recording"]["kind"] != "none":
            raise CaptureError("撮影中です")

    def _require_free(self, needed):
        if self.free_bytes() < needed + self.cfg["min_free_gb"] * 1e9:
            raise CaptureError("空き容量が足りません")

    def _controls(self):
        controls = self.camera.controls()
        if controls is None:
            raise CaptureError("カメラの設定を読めません", 503)
        return controls

    def _require_manual(self):
        controls = self._controls()
        if not controls["manual"]:
            raise CaptureError("手動露出にしてから開始してください")
        return controls

    @staticmethod
    def _number(value, label):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise CaptureError(f"{label}の値が正しくありません", 400) from None
        if not math.isfinite(value):
            raise CaptureError(f"{label}の値が正しくありません", 400)
        return value

    def _relative(self, folder):
        return str(Path(folder).relative_to(self.root))

    def _new_folder(self, kind, target):
        now = datetime.fromtimestamp(self.clock()).astimezone()
        name = f"{now.strftime('%H%M%S')}_{kind}"
        target = clean_target(target)
        if target:
            name += f"_{target}"
        folder = self.root / night_folder(now) / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _set_recording(self, kind, state, folder, **extra):
        self.store.update(recording={"kind": kind, "state": state, "path": self._relative(folder),
                                     "started_at": self.clock(), **extra})

    def _set_idle(self, state, last_kind, folder, count, message):
        self.store.update(recording={"kind": "none", "state": state, "last_kind": last_kind,
                                     "path": self._relative(folder), "count": count, "message": message})

    def _metadata(self, folder, **values):
        try:
            raw = self.mount_raw()
        except Exception:
            raw = None
        values.setdefault("controls", self.camera.controls())
        line = json.dumps({"time": self.clock(), "mount_raw": raw, **values}, ensure_ascii=False)
        with open(Path(folder) / "metadata.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _spawn(self, command, stdout=None):
        self.proc = self.popen(command, stdin=subprocess.DEVNULL, stdout=stdout)
        # 映像の送り主が替わったことを端末へ伝え、WebRTC をつなぎ直してもらう
        self.epoch += 1
        self._reassert_later()

    def _reassert_later(self):
        """配信を始めたカメラに、少し待ってから手動露出をかけ直す（Camera.reassert の説明を参照）。"""
        def run():
            waited = 0.0
            for delay in REASSERT_DELAYS:
                self.sleep(delay - waited)
                waited = delay
                if self.closing.is_set():
                    return
                try:
                    self.camera.reassert()
                except Exception as e:
                    print(f"camera reassert failed: {e}", flush=True)
        threading.Thread(target=run, daemon=True).start()

    def _start_live(self):
        if not self.closing.is_set():
            self._spawn(self.commands.live())

    def _stop_proc(self):
        proc, self.proc = self.proc, None
        if proc is None or proc.poll() is not None:
            return
        # ffmpeg は SIGINT で書きかけのファイルを閉じてから終わる
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=self.cfg["stop_timeout"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _spawn_timelapse(self):
        session = self.session
        session["last_frame"] = self.clock()
        # 起動し直したときも、露出のかけ直しが効くまでは保存しない
        session["next_shot"] = max(session["next_shot"],
                                   self.clock() + max(self.cfg["settle_seconds"], settle_seconds(session["controls"])))
        self._spawn(self.commands.timelapse(), stdout=subprocess.PIPE)
        threading.Thread(target=self._read_frames, args=(self.proc, session), daemon=True).start()

    def _read_frames(self, proc, session):
        splitter = JpegSplitter()
        while data := proc.stdout.read1(1 << 16):
            for frame in splitter.feed(data):
                session["last_frame"] = now = self.clock()
                if now < session["next_shot"] or self.session is not session:
                    continue
                # 保存に時間がかかっても撮影の間隔がずれないように、予定の時刻から数える。
                # 最初の 1 枚はカメラの起動で遅れるので、実際の時刻から数える
                base = session["next_shot"] if session["count"] else now
                session["next_shot"] = max(base + session["interval"], now)
                try:
                    self._save_frame(session, frame)
                except OSError as e:
                    print(f"timelapse: cannot save frame: {e}", flush=True)

    def _save_frame(self, session, frame):
        number = session["count"] + 1
        path = session["folder"] / f"frame_{number:05d}.jpg"
        part = path.with_suffix(".part")
        with open(part, "wb") as f:
            f.write(frame)
        os.replace(part, path)
        session["count"] = number
        self._metadata(session["folder"], file=path.name, controls=session["controls"])
        recording = self.store.get()["recording"]
        if self.session is session and recording["kind"] == "timelapse":
            self.store.update(recording={**recording, "count": number})
        threading.Thread(target=self._make_preview, args=(path,), daemon=True).start()

    def _make_preview(self, source):
        # 間に合わないときは次の画像に任せる
        if not self.preview_busy.acquire(blocking=False):
            return
        try:
            self.preview_dir.mkdir(parents=True, exist_ok=True)
            part = self.preview_dir / "latest.part.jpg"
            result = self.run(self.commands.preview(source, part), timeout=self.cfg["still_timeout"],
                              capture_output=True, text=True)
            if result.returncode == 0 and part.exists():
                os.replace(part, self.preview_dir / "latest.jpg")
                self.preview_seq += 1
        except (OSError, subprocess.SubprocessError) as e:
            print(f"cannot make preview: {e}", flush=True)
        finally:
            self.preview_busy.release()

    def _finish(self, state, message):
        session, self.session = self.session, None
        self._stop_proc()
        folder = session["folder"]
        count = session["count"]
        if session["kind"] == "video":
            count = 1 if session["part"].exists() else 0
            if count:
                os.replace(session["part"], folder / VIDEO_FILE)
            self._metadata(folder, event="end", state=state, message=message)
        self._set_idle(state, session["kind"], folder, count, message)
        self._start_live()
