#!/usr/bin/env python3
"""固定速度ごとの角速度と動き出しの遅れを、架台の読み取りから測る。

架台が実際に動く。向きと周囲を確かめてから実行し、observatory サービスは止めておくこと。
各速度で正方向に動かしてから同じ時間だけ戻すので、ほぼ元の位置に戻る。読み取りが動く
範囲は 5° に制限する。高度の読み取りは目安で、結果は方位と見比べる。
"""
import argparse
import glob
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.mount import Mount

MOVE_LIMIT = 5.0


def measure(mount, axis, direction, rate, duration):
    samples = []
    start = time.monotonic()
    mount.move(axis, direction, rate)
    while time.monotonic() - start < duration:
        mount.move(axis, direction, rate)
        samples.append((time.monotonic() - start, mount.status()[axis]))
        time.sleep(0.1)
    mount.stop("測定の区切り")
    time.sleep(2.0)
    first = samples[0][1]
    moved = [t for t, value in samples if abs(value - first) > 0.002]
    delay = moved[0] if moved else None
    late = [s for s in samples if s[0] > (delay or 0) + 1.0]
    if len(late) < 3:
        return None, delay
    speeds = [abs(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(late, late[5:])]
    return statistics.median(speeds), delay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--axes", nargs="+", default=["az", "alt"], choices=["az", "alt"])
    parser.add_argument("--rates", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "var" / "mount_rates.json"))
    args = parser.parse_args()
    port = args.port or glob.glob("/dev/serial/by-id/*Serial*")[0]
    mount = Mount(port, az_limit=MOVE_LIMIT, alt_limit=MOVE_LIMIT, hold_timeout=1.0, poll_interval=0.1)
    results = {}
    try:
        for axis in args.axes:
            for rate in args.rates:
                row = {}
                for direction in (1, -1):
                    speed, delay = measure(mount, axis, direction, rate, args.duration)
                    row["forward" if direction > 0 else "reverse"] = {"speed": speed, "delay": delay}
                    print(f"{axis} rate={rate} dir={direction} speed={speed} deg/s delay={delay} s", flush=True)
                results.setdefault(axis, {})[str(rate)] = row
    finally:
        mount.close()
    Path(args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
