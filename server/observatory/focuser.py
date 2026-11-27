"""フォーカスドライバー（Pico + 連続回転サーボ）の操作。

USB を抜けば Pico の電源が切れるので、ポートがないことを「セットされていない」とみなす。
画面からは向きと速さだけを受け、1 回の指令は Pico の `M`（指定の時間で自動停止）にする。
指令が途切れれば、回転は長くても 0.2 秒ほどで止まる。
"""
import glob
import threading

import serial

DEFAULT_PORT_GLOB = "/dev/serial/by-id/*MicroPython*"
# 速さごとの 1 回の指令の角度（度）と、押している間に繰り返す間隔（ミリ秒）。
# 回転の速さは PWM ではほとんど変えられないので、刻みと間隔で変える
SPEEDS = {"fine": (6, 500), "mid": (15, 250), "fast": (60, 150)}


class FocuserError(Exception):
    pass


class Focuser:
    def __init__(self, cfg, open_port=None):
        self.port_glob = cfg.get("port_glob", DEFAULT_PORT_GLOB)
        self.open_port = open_port or (lambda port: serial.Serial(port, 115200, timeout=0.5, write_timeout=0.5))
        self.lock = threading.Lock()
        self.link = None

    def _find(self):
        ports = sorted(glob.glob(self.port_glob))
        return ports[0] if ports else None

    def connected(self):
        return self._find() is not None

    def status(self):
        return {"connected": self.connected(), "speeds": {k: interval for k, (_, interval) in SPEEDS.items()}}

    def move(self, direction, speed):
        if direction not in (1, -1) or speed not in SPEEDS:
            raise ValueError("direction は 1 か -1、speed は fine、mid、fast で指定してください")
        self._send(f"M {direction * SPEEDS[speed][0]}")

    def stop(self):
        self._send("X")

    def close(self):
        with self.lock:
            self._drop()

    def _drop(self):
        link, self.link = self.link, None
        if link:
            try:
                link.close()
            except (OSError, serial.SerialException):
                pass

    def _send(self, command):
        with self.lock:
            port = self._find()
            if port is None:
                self._drop()
                raise FocuserError("フォーカスドライバをセットしてください")
            # 抜き差しの後は開いたままのポートが使えないので、1 回だけ開き直す
            for retry in (True, False):
                try:
                    if self.link is None:
                        self.link = self.open_port(port)
                    self.link.reset_input_buffer()
                    self.link.write(f"{command}\n".encode())
                    reply = self._reply()
                    break
                except (OSError, serial.SerialException) as e:
                    self._drop()
                    if not retry:
                        raise FocuserError(f"フォーカスドライバと通信できません: {e}") from e
            if not reply.startswith("OK"):
                self._drop()
                raise FocuserError(f"フォーカスドライバの応答が異常です: {reply or '応答なし'}")

    def _reply(self):
        # 前の移動の DONE などは読み飛ばす
        for _ in range(4):
            line = self.link.readline().decode(errors="replace").strip()
            if not line or line.startswith(("OK", "ERR")):
                return line
        return ""
