"""高速の目標移動（サーバーの導入と同じ :G 0x → :H → :M 3500 → :J、:I は送らない）の速さを測る。

0.07 秒ほどの間隔で位置を読み、時刻・位置・速さを出す。0.2 秒あたりの最大の動き（見張りの
読み取りの間隔）も出す。行き過ぎ（指定量 + 0.5°）か時間切れで :K を送り、最後に必ず両軸を止める。
observatory.service を止めてから使う（シリアルは 1 プロセスしか開けない）。

    python3 tools/measure_goto_speed.py --axis 1 --deg -10
"""
import argparse
import glob
import sys
import time

import serial

from motor_jog import cmd, hex24, position, running, stop_all
from probe_motor import le24

MAX_DEG = 30.0
MARGIN_DEG = 0.5
BRAKE_HIGH = 3500


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["1", "2"], required=True)
    ap.add_argument("--deg", type=float, required=True, help="移動量（符号つき）")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--port")
    args = ap.parse_args()
    if not 0 < abs(args.deg) <= MAX_DEG:
        sys.exit(f"移動量は 0〜{MAX_DEG} 度")
    name = args.port or glob.glob("/dev/serial/by-id/*SynHub*")[0]
    axis = args.axis
    with serial.Serial(name, 9600, timeout=1.0) as port:
        time.sleep(0.2)
        try:
            cpr = le24(cmd(port, "a", axis))
            k = cpr / 360.0
            if running(port, axis):
                sys.exit("その軸はすでに動いている")
            steps = round(abs(args.deg) * k)
            start = position(port, axis)
            target = start + (steps if args.deg > 0 else -steps)
            limit = (abs(args.deg) + MARGIN_DEG) * k
            cmd(port, "G", axis, "0" + ("0" if args.deg > 0 else "1"))
            cmd(port, "H", axis, hex24(steps))
            cmd(port, "M", axis, hex24(BRAKE_HIGH))
            print(f"軸 {axis}  開始 {start / k:+.3f}°  目標 {target / k:+.3f}°（{args.deg:+.2f}°）")
            t0 = time.monotonic()
            cmd(port, "J", axis)
            samples = [(0.0, start)]
            stopped_by = None
            while True:
                now = time.monotonic() - t0
                pos = position(port, axis)
                samples.append((now, pos))
                if abs(pos - start) > limit:
                    stopped_by = "行き過ぎ"
                    break
                if now > args.timeout:
                    stopped_by = "時間切れ"
                    break
                if not running(port, axis):
                    break
            done = time.monotonic() - t0
            if stopped_by:
                cmd(port, "K", axis)
                print(f"{stopped_by}で停止")
            time.sleep(0.5)
            end = position(port, axis)
        finally:
            stop_all(port)
    print("  時刻   位置°     速さ°/秒")
    peak = 0.0
    for (ta, pa), (tb, pb) in zip(samples, samples[1:]):
        v = (pb - pa) / k / (tb - ta) if tb > ta else 0.0
        peak = max(peak, abs(v))
        print(f"{tb:6.2f} {pb / k:+9.3f} {v:+9.2f}")
    worst = 0.0
    for i, (ta, pa) in enumerate(samples):
        for tb, pb in samples[i + 1:]:
            if tb - ta > 0.2:
                break
            worst = max(worst, abs(pb - pa) / k)
    print(f"終了 {end / k:+.3f}°  目標との差 {(end - target) / k * 3600:+.1f}″  {done:.2f} 秒  "
          f"最高 約 {peak:.2f}°/秒  0.2 秒以内の最大の動き {worst:.2f}°")


if __name__ == "__main__":
    main()
