"""Sky-Watcher のモーター基板の命令を送受信する部品（直結版）。

命令は ":" + 文字 + 軸（"1" 方位、"2" 高度）+ データ + CR。返事は "=" + データ + CR、
誤りは "!" + 番号 + CR。24 ビットの値は 16 進 6 桁で、下位のバイトが先に来る。
位置は電源投入時が 0x800000 で、その向きを 0 とする。

SynHub（USB CDC）では命令は折り返されない。ハンドコントローラーの PC Direct モードでは、
送った命令がそのまま返ってから返事が来るので、それは読み捨てる。

この部品は送受信と返事の検査だけを受け持ち、安全の判断はしない（safety.py と direct_mount.py）。
"""
import re
import threading

import serial

from .mount import MountError

CENTER = 0x800000
AXES = {"az": "1", "alt": "2"}
BAUD = 9600
REPLY = re.compile(rb"([=!])([0-9A-F]*)\r")

# :G の 1 文字目（INDI の注釈と 2026-11-14 の実測で確認）
GOTO_FAST, SLEW_SLOW, GOTO_SLOW, SLEW_FAST = "0", "1", "2", "3"


class MotorError(MountError):
    pass


def le24(text):
    """6 桁の 16 進（下位バイトが先）を数値にする。"""
    b = bytes.fromhex(text)
    return b[0] | (b[1] << 8) | (b[2] << 16)


def hex24(value):
    if not 0 <= value <= 0xFFFFFF:
        raise ValueError(f"24 ビットに収まらない値: {value}")
    return f"{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


class MotorBoard:
    """1 本のシリアルで基板と話す。複数のスレッドから呼んでよい。"""

    def __init__(self, port, timeout=0.5, retries=1, link=None):
        # link はテスト用に差し替えられる（read_until / write / reset_input_buffer / close を持つもの）
        self.link = link or serial.Serial(port, BAUD, timeout=timeout)
        self.port = port
        self.retries = retries
        self.lock = threading.Lock()
        self.bad_replies = 0  # 形のおかしい返事の累計（見張りと記録に使う）

    def close(self):
        self.link.close()

    def _once(self, line):
        self.link.reset_input_buffer()
        self.link.write(line)
        reply = self.link.read_until(b"\r")
        if reply.endswith(line):  # PC Direct の折り返し
            reply = self.link.read_until(b"\r")
        return reply

    def command(self, cmd, axis, data=""):
        """命令を送り、返事のデータ部分を返す。形がおかしければ読み直し、だめなら MotorError。"""
        line = f":{cmd}{AXES.get(axis, axis)}{data}\r".encode()
        last = None
        with self.lock:
            for _ in range(self.retries + 1):
                reply = self._once(line)
                match = REPLY.fullmatch(reply)
                if match and match.group(1) == b"=":
                    return match.group(2).decode()
                if match:
                    # 基板が命令を断った（例: 動いている軸への :H）。読み直しても同じなので返す
                    raise MotorError(f"{line!r} を基板が断った: !{match.group(2).decode()}")
                self.bad_replies += 1
                last = reply
        raise MotorError(f"{line!r} への返事がおかしい: {last!r}")

    # 読み取り
    def version(self):
        """(版の文字列, 機種コード)。0209A1 → ("2.09", 0xA1)。"""
        data = self.command("e", "az")
        if len(data) != 6:
            raise MotorError(f"版の返事がおかしい: {data!r}")
        return f"{int(data[0:2], 16)}.{int(data[2:4], 16):02d}", int(data[4:6], 16)

    def cpr(self, axis):
        return le24(self.command("a", axis))

    def timer_freq(self):
        return le24(self.command("b", "az"))

    def high_ratio(self, axis):
        return int(self.command("g", axis), 16)

    def position(self, axis):
        """電源投入時からの刻み数（符号つき）。"""
        data = self.command("j", axis)
        if len(data) != 6:
            raise MotorError(f"位置の返事がおかしい: {data!r}")
        return le24(data) - CENTER

    def status(self, axis):
        data = self.command("f", axis)
        if len(data) != 3:
            raise MotorError(f"状態の返事がおかしい: {data!r}")
        a, b, c = (int(ch, 16) for ch in data)
        return {"slew": bool(a & 1), "reverse": bool(a & 2), "fast": bool(a & 4),
                "running": bool(b & 1), "blocked": bool(b & 2), "initialized": bool(c & 1)}

    # 操作
    def initialize(self, axis):
        self.command("F", axis)

    def set_motion(self, axis, mode, forward):
        self.command("G", axis, mode + ("0" if forward else "1"))

    def set_period(self, axis, period):
        self.command("I", axis, hex24(max(1, int(period))))

    def set_goto_increment(self, axis, steps):
        self.command("H", axis, hex24(int(steps)))

    def set_brake_increment(self, axis, steps):
        self.command("M", axis, hex24(int(steps)))

    def start(self, axis):
        self.command("J", axis)

    def stop(self, axis):
        self.command("K", axis)

    def instant_stop(self, axis):
        self.command("L", axis)
