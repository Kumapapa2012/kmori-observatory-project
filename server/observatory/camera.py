"""カメラの露出とゲインの設定、配信の状態の確認。映像そのものは MediaMTX が扱う。"""
import json
import subprocess
import urllib.error
import urllib.request

AUTO, MANUAL = 3, 1
# 露出は 100µs 単位。主鏡の SV205 の範囲で、ファインダーの ELP は設定ファイルで狭める
EXPOSURE_RANGE = (1, 10000)
GAIN_RANGE = (0, 128)


class Camera:
    def __init__(self, device, mediamtx_api, path="camera", exposure_range=EXPOSURE_RANGE, gain_range=GAIN_RANGE):
        self.device = device
        self.mediamtx_api = mediamtx_api
        self.path = path
        self.exposure_range = tuple(exposure_range)
        self.gain_range = tuple(gain_range)

    def controls(self):
        """読めないときは None を返す。"""
        try:
            out = subprocess.run(
                ["v4l2-ctl", "-d", self.device, "-C", "auto_exposure,exposure_time_absolute,gain"],
                capture_output=True, text=True, check=True, timeout=3).stdout
            values = {}
            for line in out.splitlines():
                key, _, value = line.partition(":")
                values[key.strip()] = int(value.split()[0])
            return {"manual": values["auto_exposure"] == MANUAL,
                    "exposure": values["exposure_time_absolute"], "gain": values["gain"],
                    "exposure_max": self.exposure_range[1], "gain_max": self.gain_range[1]}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
            return None

    def _set(self, name, value):
        # 複数の項目を 1 回で設定すると順序の都合で拒否されるため、1 項目ずつ設定する
        subprocess.run(["v4l2-ctl", "-d", self.device, "-c", f"{name}={value}"],
                       capture_output=True, text=True, check=True, timeout=3)

    def apply(self, manual=None, exposure=None, gain=None):
        if exposure is not None and not self.exposure_range[0] <= exposure <= self.exposure_range[1]:
            raise ValueError("exposure out of range")
        if gain is not None and not self.gain_range[0] <= gain <= self.gain_range[1]:
            raise ValueError("gain out of range")
        if manual is not None:
            self._set("auto_exposure", MANUAL if manual else AUTO)
        if exposure is not None:
            self._set("exposure_time_absolute", exposure)
        if gain is not None:
            self._set("gain", gain)

    def reassert(self):
        """配信を始め直した直後に、手動露出の設定をかけ直す。

        SV205 は、配信の開始（形式の切り替えを含む）のあとは、自動 → 手動と切り替えるまで手動露出の値を使わず、
        報告する値は設定どおりのまま、映像はほぼ真っ黒になる（2026-11-07 に実機で確認）。
        自動露出のときは何もしない。かけ直したら True を返す。"""
        controls = self.controls()
        if not controls or not controls["manual"]:
            return False
        self._set("auto_exposure", AUTO)
        self._set("auto_exposure", MANUAL)
        self._set("exposure_time_absolute", controls["exposure"])
        self._set("gain", controls["gain"])
        return True

    def stream_online(self):
        try:
            with urllib.request.urlopen(f"{self.mediamtx_api}/v3/paths/get/{self.path}", timeout=1) as r:
                return bool(json.load(r).get("ready"))
        except (OSError, ValueError, urllib.error.URLError):
            return False
