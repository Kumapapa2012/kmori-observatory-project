"""追尾の映像補正。基準画像と今の画像のずれを相関で測り、追尾の速度を少し変える。

大気の揺れを追いかけないよう、数秒分の画像を平均してから測り、ずれの一部だけを反映する。
位置を戻す動きはガタに入るので使わず、速度だけを調整する。カメラは鏡筒に固定されているので、
視野が回転しても画面の横は方位、縦は高度のままで、補正の向きは変わらない。
"""
import math
import subprocess
import threading
import time

import numpy as np

WIDTH, HEIGHT = 480, 270
BAND_HIGH, BAND_LOW = 0.06, 0.008  # 周期/画素。細かいノイズと JPEG の格子、全体の明暗を除く
MIN_PEAK = 5.0
MAX_JUMP = 80.0  # 1 回の測定で飛んでよいずれ（秒角）。超えたら別の模様に合ったとみなす
PERIOD = 15.0  # 補正の間隔（秒）
WINDOW = 5.0  # 平均する時間（秒）
SETTLE = 3.0  # 動かした後に待つ時間（秒）
MAX_REFRESH_ANGLE = 0.25  # 基準を取り直す視野回転の角度（度）
REFRESH_RANGE = (60.0, 300.0)  # 基準を取り直す間隔の範囲（秒）
# 1 画素あたりの秒角（幅 480 に縮小した値）。タイムラプス中は視野が変わる
SCALES = {"live": (16.5 * 60 / WIDTH, 9.3 * 60 / HEIGHT), "timelapse": (14.5 * 60 / WIDTH, 9.6 * 60 / HEIGHT)}

_fy = np.fft.fftfreq(HEIGHT)[:, None]
_fx = np.fft.rfftfreq(WIDTH)[None, :]
_r2 = _fx ** 2 + _fy ** 2
_BAND = np.exp(-_r2 / (2 * BAND_HIGH ** 2)) - np.exp(-_r2 / (2 * BAND_LOW ** 2))
_WINDOW = np.outer(np.hanning(HEIGHT), np.hanning(WIDTH))


def measure_shift(reference, image):
    """image が reference からずれた量（画素）と、相関の山の高さを返す。"""
    a = np.fft.rfft2((image - image.mean()) * _WINDOW) * _BAND
    b = np.fft.rfft2((reference - reference.mean()) * _WINDOW) * _BAND
    c = np.fft.irfft2(a * np.conj(b), s=(HEIGHT, WIDTH))
    peak = (c.max() - c.mean()) / (c.std() + 1e-9)
    dy, dx = np.unravel_index(np.argmax(c), c.shape)
    dy, dx = int(dy), int(dx)
    if dy > HEIGHT / 2:
        dy -= HEIGHT
    if dx > WIDTH / 2:
        dx -= WIDTH
    return dx, dy, float(peak)


def field_rotation_rate(latitude, az, alt):
    """視野の回転の速さの大きさ（度/時）を返す。"""
    cos_alt = max(math.cos(math.radians(alt)), 0.02)
    return abs(15.04 * math.cos(math.radians(latitude)) * math.cos(math.radians(az)) / cos_alt)


def refresh_interval(rate):
    """回転が MAX_REFRESH_ANGLE に達する時間を、基準を取り直す間隔にする。"""
    if rate <= 0:
        return REFRESH_RANGE[1]
    return min(max(MAX_REFRESH_ANGLE / rate * 3600.0, REFRESH_RANGE[0]), REFRESH_RANGE[1])


class Controller:
    """ずれから追尾の速度の補正（秒角/秒）を求める。"""

    def __init__(self, period=PERIOD, gain_p=0.25, gain_i=0.15, dead_band=2.0, limit=5.0):
        self.period = period
        self.gain_p = gain_p
        self.gain_i = gain_i
        self.dead_band = dead_band
        self.limit = limit
        self.reset()

    def reset(self):
        self.integral = {"az": 0.0, "alt": 0.0}
        self.output = {"az": 0.0, "alt": 0.0}

    def update(self, image_x, image_y, cos_alt):
        """image_x、image_y は天体が画面で右、下へずれた量（秒角）。"""
        # 右へずれたら右（方位 +）へ、下へずれたら下（高度 −）へ向きを動かす
        errors = {"az": image_x / max(cos_alt, 0.1), "alt": -image_y}
        for axis, error in errors.items():
            if abs(error) < self.dead_band:
                error = 0.0
            rate = error / self.period
            self.integral[axis] = self._clamp(self.integral[axis] + self.gain_i * rate)
            self.output[axis] = self._clamp(self.integral[axis] + self.gain_p * rate)
        return dict(self.output)

    def hold(self):
        """測れないときは、積み上げた分だけを残す。"""
        self.output = dict(self.integral)

    def _clamp(self, value):
        return max(-self.limit, min(self.limit, value))


def apply_correction(base, correction):
    """補正を加える。補正で追尾の向きが逆転するとガタに入るので、0 で止める。"""
    total = base + correction
    return 0.0 if base * total < 0 else total


def hold_correction(error, gain=0.05, limit=60.0, dead_band=0.002):
    """追尾中に、保つべき位置との差（度）を詰める速さ（秒角/秒）。

    速さだけの追尾は、計算の丸めや基板の速さの刻みでずれが積もる。差に gain（1/秒）を掛けた速さで
    詰め（0.1° なら 18″/秒、約 20 秒で詰まる）、limit を超えないようにする。dead_band 未満は 0。"""
    if abs(error) < dead_band:
        return 0.0
    return max(-limit, min(limit, error * gain * 3600.0))


class FrameReader:
    """配信から縮小したキーフレームだけを読む。デコードの負荷を抑えるため 1 秒に 1 枚程度になる。"""

    def __init__(self, url):
        self.url = url
        self.proc = None

    def open(self):
        self.proc = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-loglevel", "quiet", "-skip_frame", "nokey", "-rtsp_transport", "tcp",
             "-i", self.url, "-fps_mode", "passthrough",
             "-vf", f"scale={WIDTH}:{HEIGHT},format=gray", "-f", "rawvideo", "pipe:1"],
            stdout=subprocess.PIPE)

    def read(self):
        data = b""
        size = WIDTH * HEIGHT
        while len(data) < size:
            chunk = self.proc.stdout.read(size - len(data))
            if not chunk:
                return None
            data += chunk
        return np.frombuffer(data, np.uint8).reshape(HEIGHT, WIDTH).astype(np.float32)

    def close(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


class Guider:
    """context() は {"paused", "mode", "cos_alt", "rotation"} を返す関数。"""

    def __init__(self, reader, context, period=PERIOD, window=WINDOW, settle=SETTLE):
        self.reader = reader
        self.context = context
        self.period = period
        self.window = window
        self.settle = settle
        self.controller = Controller(period)
        self.lock = threading.Lock()
        self.status = {"state": "off", "error_x": None, "error_y": None, "peak": None}
        self.thread = None
        self.running = threading.Event()

    def start(self):
        self.stop()
        self.controller.reset()
        self.running.set()
        self._set(state="starting", error_x=None, error_y=None, peak=None)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running.clear()
        self.reader.close()
        if self.thread:
            self.thread.join(timeout=3)
        self.thread = None
        self.controller.reset()
        self._set(state="off")

    def correction(self):
        with self.lock:
            return dict(self.controller.output)

    def snapshot(self):
        with self.lock:
            return {**self.status, "correction": dict(self.controller.output)}

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def _run(self):
        while self.running.is_set():
            self.reader.open()
            try:
                self._guide()
            except Exception as e:
                print(f"guiding error: {e}", flush=True)
            finally:
                self.reader.close()
            # 撮影の切り替えで配信が途切れたら、つなぎ直して基準から取り直す
            if self.running.is_set():
                self._set(state="waiting")
                time.sleep(1.0)

    def _guide(self):
        reference = None
        reference_time = 0.0
        offset = (0.0, 0.0)  # 基準を取り直す前までのずれ（秒角）
        last = (0.0, 0.0)
        frames = []
        settled_at = time.monotonic() + self.settle
        due = 0.0
        while self.running.is_set():
            frame = self.reader.read()
            if frame is None:
                return
            now = time.monotonic()
            ctx = self.context()
            if ctx["paused"]:
                # 手動で動かしたら、その位置を新しい基準にする
                reference = None
                frames.clear()
                settled_at = now + self.settle
                with self.lock:
                    self.controller.hold()
                self._set(state="paused")
                continue
            if now < settled_at:
                continue
            if reference is not None and now < due - self.window:
                continue
            frames.append(frame)
            if len(frames) < 2 or now - (due - self.window if reference is not None else settled_at) < self.window:
                continue
            average = np.mean(frames, axis=0)
            frames.clear()
            if reference is None:
                reference, reference_time, offset, last = average, now, (0.0, 0.0), (0.0, 0.0)
                due = now + self.period
                self._set(state="guiding", error_x=0.0, error_y=0.0, peak=None)
                print("guiding: reference set", flush=True)
                continue
            due = now + self.period
            dx, dy, peak = measure_shift(reference, average)
            scale = SCALES.get(ctx["mode"], SCALES["live"])
            x, y = offset[0] + dx * scale[0], offset[1] + dy * scale[1]
            if peak < MIN_PEAK or math.hypot(x - last[0], y - last[1]) > MAX_JUMP:
                with self.lock:
                    self.controller.hold()
                self._set(state="lost", peak=peak)
                print(f"guiding: rejected x={x:.1f} y={y:.1f} peak={peak:.1f}", flush=True)
                continue
            last = (x, y)
            with self.lock:
                output = self.controller.update(x, y, ctx["cos_alt"])
            self._set(state="guiding", error_x=x, error_y=y, peak=peak)
            print(f"guiding: x={x:.1f} y={y:.1f} peak={peak:.1f} az={output['az']:.2f} alt={output['alt']:.2f}", flush=True)
            if now - reference_time > refresh_interval(ctx["rotation"]):
                reference, reference_time, offset = average, now, (x, y)
                print("guiding: reference refreshed", flush=True)
