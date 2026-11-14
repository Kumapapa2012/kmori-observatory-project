"""モーター基板（SE-AT90M、版 2.09、0xA1）の代役。motor.MotorBoard の link に差し込む。

2026-11-14 の実測に合わせた動き:
- 定速の移動（:G 1x/3x）は :I の値どおりの速さ（高速は倍率 32）。
- 目標移動（:G 0x/2x）は :I に従わず、低速 0.6°/秒、高速 2.5°/秒で、目標の 7 刻み手前で止まる。
- 電源投入直後は未初期化。未初期化のときの目標移動は約 0.35 秒で止まる。
- 動いている軸への :G と :H は断る（"!2"）。:I は動いている間も受け付ける。
"""
import threading
import time

CENTER = 0x800000
CPR = 865050
FREQ = 20000
RATIO = 32


def le24(value):
    value &= 0xFFFFFF
    return f"{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


class Axis:
    def __init__(self):
        self.pos = 0.0  # 刻み（電源投入時が 0）
        self.running = False
        self.mode = "1"
        self.forward = True
        self.period = 1
        self.increment = 0
        self.target = None
        self.initialized = False
        self.started = 0.0
        self.commands = []


class FakeMotorBoard:
    def __init__(self, initialized=False):
        self.axes = {"1": Axis(), "2": Axis()}
        for a in self.axes.values():
            a.initialized = initialized
        self.lock = threading.Lock()
        self.last = time.monotonic()
        self.pending = b""
        self.garble = 0  # 次の n 回の返事を化けさせる
        self.silent = False
        self.closed = False
        self.log = []

    # 物理
    def speed(self, a):
        """刻み/秒（符号つき）。"""
        if not a.running:
            return 0.0
        sign = 1 if a.forward else -1
        if a.mode in ("1", "3"):
            return sign * FREQ * (RATIO if a.mode == "3" else 1) / a.period
        deg = 2.5 if a.mode == "0" else 0.6
        return sign * deg * CPR / 360

    def advance(self):
        now = time.monotonic()
        dt = now - self.last
        self.last = now
        for a in self.axes.values():
            if not a.running:
                continue
            a.pos += self.speed(a) * dt
            if a.mode in ("0", "2"):
                if not a.initialized and now - a.started > 0.35:
                    a.running = False
                elif a.target is not None and (a.pos - a.target) * (1 if a.forward else -1) >= 0:
                    a.pos = a.target
                    a.running = False

    def external_move(self, axis, steps):
        """ほかの経路（Wi-Fi のアプリなど）から動かされたことにする。"""
        with self.lock:
            self.advance()
            self.axes[axis].pos += steps

    def power_glitch(self, keep_position=True):
        with self.lock:
            for a in self.axes.values():
                a.initialized = False
                a.running = False
                if not keep_position:
                    a.pos = 0.0

    # link の口
    def reset_input_buffer(self):
        self.pending = b""

    def write(self, line):
        with self.lock:
            self.advance()
            self.pending = self.handle(line.decode())
            self.log.append(line.decode().strip())

    def read_until(self, end=b"\r"):
        reply, self.pending = self.pending, b""
        if self.silent:
            return b""
        if self.garble:
            self.garble -= 1
            return b"=\xff\x00?\r"
        return reply

    def close(self):
        self.closed = True

    def handle(self, line):
        cmd, ax, data = line[1], line[2], line[3:-1]
        a = self.axes.get(ax)
        if a is None:
            return b"!0\r"
        a.commands.append(cmd + data)
        if cmd == "e":
            return b"=0209A1\r"
        if cmd == "a":
            return f"={le24(CPR)}\r".encode()
        if cmd == "b":
            return f"={le24(FREQ)}\r".encode()
        if cmd == "g":
            return f"={RATIO:02X}\r".encode()
        if cmd == "j":
            return f"={le24(round(a.pos) + CENTER)}\r".encode()
        if cmd == "f":
            first = (0 if a.mode in ("0", "2") else 1) | (0 if a.forward else 2) | (4 if a.mode in ("0", "3") else 0)
            return f"={first:X}{1 if a.running else 0}{1 if a.initialized else 0}\r".encode()
        if cmd == "F":
            a.initialized = True
            return b"=\r"
        if cmd == "G":
            if a.running:
                return b"!2\r"
            a.mode, a.forward = data[0], data[1] == "0"
            return b"=\r"
        if cmd == "I":
            b = bytes.fromhex(data)
            a.period = max(1, b[0] | b[1] << 8 | b[2] << 16)
            return b"=\r"
        if cmd == "H":
            if a.running:
                return b"!2\r"
            b = bytes.fromhex(data)
            a.increment = b[0] | b[1] << 8 | b[2] << 16
            return b"=\r"
        if cmd == "M":
            return b"=\r"
        if cmd == "J":
            if a.mode in ("0", "2"):
                sign = 1 if a.forward else -1
                a.target = a.pos + sign * (a.increment - 7)
            else:
                a.target = None
            a.running = True
            a.started = time.monotonic()
            return b"=\r"
        if cmd in ("K", "L"):
            a.running = False
            return b"=\r"
        return b"!0\r"
