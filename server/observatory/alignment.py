"""1 つの基準星による校正。架台の読み取りと計算した天体の位置の差を保持する。

求まるのは方位と高度のずれだけで、架台の傾きは補正しない。高度の読み取りは目安で、
固定ねじが空転すると校正は黙って外れる。
"""
import time

# 架台の時計は電源投入からの経過で進むので、実時間との差が変われば電源が入り直されたと分かる
CLOCK_TOLERANCE = 300.0


def wrap360(angle):
    return angle % 360.0


def wrap180(angle):
    return (angle + 180.0) % 360.0 - 180.0


def register(star, sky_position, raw, clock_time, now=None):
    now = time.time() if now is None else now
    return {
        "star": star,
        "time": now,
        "az_offset": wrap180(sky_position[0] - raw["az"]),
        "alt_offset": sky_position[1] - raw["alt"],
        "clock_offset": clock_time - now,
    }


def pointing(alignment, raw):
    """校正の結果から現在の向きを求める。"""
    return {"az": wrap360(raw["az"] + alignment["az_offset"]),
            "alt": wrap180(raw["alt"] + alignment["alt_offset"])}


def still_valid(alignment, clock_time, now=None):
    now = time.time() if now is None else now
    return abs(clock_time - now - alignment["clock_offset"]) <= CLOCK_TOLERANCE
