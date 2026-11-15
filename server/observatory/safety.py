"""架台の安全装置。接続方式によらず「軸の角度」（電源投入時の向きからの度）で判断する。

決めた内容は計画書の「段階 2 の決定」（2026-11-14）。

- 向きの基準: 既定は北・水平で電源を入れた（軸の 0 が北・水平）。観測地に登録した目標
  （自宅ではスカイツリー）で合わせることもできる。基準を選ぶまでは制限モード。
- 範囲: 高度 −5°〜+92°（本当の高度）、方位は軸の 0 から ±180°（ケーブルの巻き付き防止）。
  制限モードでは軸の 0 から方位 ±30°、高度 ±20°、低速だけ。
- 見張り: 飛び、頼んでいない動き、電源の瞬断、停滞、読み取りの失敗の続き。
"""
import math
from dataclasses import dataclass, field

from .mount import MountError

AXES = ("az", "alt")


class SafetyError(MountError):
    pass


@dataclass
class SafetyConfig:
    alt_min: float = -5.0
    alt_max: float = 92.0
    az_span: float = 180.0
    restricted_az: float = 30.0
    restricted_alt: float = 20.0
    restricted_rate: float = 0.3  # 度/秒
    max_rate: float = 3.0  # 十字キーと導入の速さの上限（度/秒）
    track_max_rate: float = 0.05  # 追尾の速さの上限（度/秒）
    max_move_deg: float = 45.0
    max_move_seconds: float = 120.0
    jump_margin: float = 0.5  # 速さ × 時間に足す余裕（度）
    jump_speed: float = 6.0  # 基板が動いている軸で許す速さ（度/秒）。高速の目標移動より速い
    idle_motion: float = 0.05  # 止めているときに許す動き（度）
    settle_seconds: float = 1.5  # 止めてから止まりきるまで見逃す時間（秒）
    stall_seconds: float = 2.0
    stall_min_rate: float = 0.05  # これより遅い動きは停滞の判定をしない（度/秒）
    max_read_failures: int = 3
    sun_min_sep: float = 15.0

    @classmethod
    def from_dict(cls, d):
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Reference:
    """軸の角度から本当の方位・高度を出すずれ。kind が None なら未確定（制限モード）。"""
    kind: str = None  # "power_on"（北・水平で電源投入）/ "landmark"（目標で合わせた）
    az_offset: float = 0.0
    alt_offset: float = 0.0
    label: str = ""

    def pointing(self, axis_deg):
        return {"az": axis_deg["az"] + self.az_offset, "alt": axis_deg["alt"] + self.alt_offset}

    def to_axis(self, az, alt):
        return {"az": az - self.az_offset, "alt": alt - self.alt_offset}


def power_on_reference():
    return Reference(kind="power_on", label="北・水平で電源投入")


class Envelope:
    """動いてよい範囲（軸の角度）。"""

    def __init__(self, cfg, reference=None):
        self.cfg = cfg
        self.reference = reference or Reference()

    @property
    def restricted(self):
        return self.reference.kind is None

    def axis_range(self, axis):
        c = self.cfg
        if self.restricted:
            span = c.restricted_az if axis == "az" else c.restricted_alt
            return (-span, span)
        if axis == "az":
            return (-c.az_span, c.az_span)
        return (c.alt_min - self.reference.alt_offset, c.alt_max - self.reference.alt_offset)

    def max_rate(self):
        return self.cfg.restricted_rate if self.restricted else self.cfg.max_rate

    def check_target(self, axis, target):
        lo, hi = self.axis_range(axis)
        if not lo <= target <= hi:
            mode = "制限モード" if self.restricted else "範囲"
            raise SafetyError(f"{axis}: {target:+.2f}° は{mode}（{lo:+.1f}〜{hi:+.1f}°）の外です")

    def room(self, axis, position, direction):
        """その向きにあと何度動けるか（0 以下なら動けない）。"""
        lo, hi = self.axis_range(axis)
        return hi - position if direction > 0 else position - lo


def angular_separation(az1, alt1, az2, alt2):
    a1, h1, a2, h2 = (math.radians(v) for v in (az1, alt1, az2, alt2))
    c = math.sin(h1) * math.sin(h2) + math.cos(h1) * math.cos(h2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def check_sun(cfg, reference, target_axis, sun_altaz):
    """基準が確定しているとき、目標が太陽に近すぎれば SafetyError。sun_altaz は (方位, 高度)。"""
    if reference.kind is None or sun_altaz is None or sun_altaz[1] < -cfg.sun_min_sep:
        return
    p = reference.pointing(target_axis)
    sep = angular_separation(p["az"], p["alt"], sun_altaz[0], sun_altaz[1])
    if sep < cfg.sun_min_sep:
        raise SafetyError(f"太陽から {sep:.1f}° の向きです（{cfg.sun_min_sep:.0f}° 以内には向けません）")


@dataclass
class Monitor:
    """読み取りを見張り、止めるべき理由を返す。commanded は軸ごとの「今出している最大の速さ（度/秒）」で、
    止めている軸は 0。"""
    cfg: SafetyConfig
    last: dict = None
    last_time: float = None
    rest: dict = field(default_factory=dict)  # 止めている軸の止まった位置
    stopped_at: dict = field(default_factory=dict)  # 軸を止めた時刻
    moved_at: dict = field(default_factory=dict)  # 動かしている軸の位置が最後に変わった時刻
    failures: int = 0

    def read_failed(self):
        self.failures += 1
        if self.failures >= self.cfg.max_read_failures:
            return f"読み取りに {self.failures} 回続けて失敗したため"
        return None

    def mark_stopped(self, axis, now):
        self.stopped_at[axis] = now
        self.rest.pop(axis, None)

    def update(self, positions, status, commanded, now):
        """positions は軸の角度（度）、status は軸ごとの基板の状態、commanded は度/秒。"""
        self.failures = 0
        reason = None
        for axis in AXES:
            if not status[axis]["initialized"]:
                reason = reason or "基板が未初期化に戻った（電源の瞬断の可能性）ため"
        if self.last is not None and reason is None:
            dt = max(now - self.last_time, 0.0)
            for axis in AXES:
                delta = positions[axis] - self.last[axis]
                speed = max(commanded.get(axis, 0.0), self.cfg.jump_speed if status[axis]["running"] else 0.0)
                if abs(delta) > speed * dt + self.cfg.jump_margin:
                    reason = f"{axis} の読み取りが {delta:+.2f}° 飛んだため"
                    break
                if commanded.get(axis, 0.0) > 0:
                    self.rest.pop(axis, None)
                    if abs(delta) > 1e-4 or axis not in self.moved_at:
                        self.moved_at[axis] = now
                    if (commanded[axis] >= self.cfg.stall_min_rate
                            and now - self.moved_at[axis] > self.cfg.stall_seconds):
                        reason = f"{axis} を動かしているのに {self.cfg.stall_seconds:.0f} 秒間位置が変わらないため"
                        break
                else:
                    self.moved_at.pop(axis, None)
                    settling = now - self.stopped_at.get(axis, -1e9) < self.cfg.settle_seconds
                    if settling or status[axis]["running"] and axis not in self.rest:
                        self.rest[axis] = positions[axis]
                        continue
                    if axis not in self.rest:
                        self.rest[axis] = positions[axis]
                    elif abs(positions[axis] - self.rest[axis]) > self.cfg.idle_motion:
                        reason = f"{axis} が止めているのに {positions[axis] - self.rest[axis]:+.2f}° 動いたため"
                        break
        self.last = dict(positions)
        self.last_time = now
        return reason
