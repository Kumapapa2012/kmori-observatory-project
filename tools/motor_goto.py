"""PC Direct でモーター基板の目標位置への移動（:G 0x（高速）/2x（低速） → :H → :M → :J）を試す。

移動量（度）を渡すと、基板が自分で加速・減速して止まる。こちらは位置を見張るだけで、
行き過ぎ（指定量 + 余裕）か時間切れのときだけ :K を送る。最後に必ず両軸を止める。

    python3 tools/motor_goto.py --axis 1 --deg 2 [--high] [--rate 0.3]
"""
import argparse
import glob
import sys
import time

import serial

from motor_jog import cmd, hex24, position, running, stop_all
from probe_motor import le24

MAX_DEG = 5.0
MARGIN_DEG = 0.3
BRAKE_LOW = 200  # 刻み。INDI の低速の値に合わせる
BRAKE_HIGH = 3500  # 刻み。INDI の高速の値に合わせる


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["1", "2"], required=True)
    ap.add_argument("--deg", type=float, required=True, help="移動量（符号つき）")
    ap.add_argument("--high", action="store_true", help="高速の目標移動（:G 0x）")
    ap.add_argument("--rate", type=float, default=0.3, help="速さ（度/秒、:I で指定。高速は倍率をかける）")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--port")
    args = ap.parse_args()
    if not 0 < abs(args.deg) <= MAX_DEG:
        sys.exit(f"移動量は 0〜{MAX_DEG} 度")
    if not 0 < args.rate <= (3.0 if args.high else 0.5):
        sys.exit("速さは低速 0〜0.5、高速 0〜3 度/秒")
    name = args.port or glob.glob("/dev/serial/by-id/*Serial*")[0]
    axis = args.axis
    with serial.Serial(name, 9600, timeout=1.0) as port:
        time.sleep(0.2)
        try:
            cpr = le24(cmd(port, "a", axis))
            freq = le24(cmd(port, "b", "1"))
            if running(port, axis):
                sys.exit("その軸はすでに動いている")
            steps = round(abs(args.deg) * cpr / 360.0)
            start = position(port, axis)
            target = start + (steps if args.deg > 0 else -steps)
            limit = (abs(args.deg) + MARGIN_DEG) * cpr / 360.0
            mode = "0" if args.high else "2"  # 1 文字目: 0 高速の目標移動、1 低速の定速、2 低速の目標移動、3 高速の定速（INDI の注釈）
            cmd(port, "G", axis, mode + ("0" if args.deg > 0 else "1"))
            ratio = int(cmd(port, "g", axis), 16) if args.high else 1
            # :I を毎回指定する（前の値が残っていると、その速さで動く）
            cmd(port, "I", axis, hex24(round(freq * ratio / (args.rate * cpr / 360.0))))
            cmd(port, "H", axis, hex24(steps))
            cmd(port, "M", axis, hex24(BRAKE_HIGH if args.high else BRAKE_LOW))
            print(f"開始 {start:+d}  目標 {target:+d}（{steps} 刻み）  {'高速' if args.high else '低速'}")
            t0 = time.time()
            cmd(port, "J", axis)
            last = start
            peak = 0.0
            while True:
                time.sleep(0.1)
                now = time.time() - t0
                pos = position(port, axis)
                speed = (pos - last) * 360.0 / cpr / 0.1
                peak = max(peak, abs(speed))
                last = pos
                if abs(pos - start) > limit:
                    print(f"{now:.2f} 秒 行き過ぎ {pos - target:+d} 刻みで停止")
                    break
                if now > args.timeout:
                    print("時間切れで停止")
                    break
                if not running(port, axis):
                    break
            done = time.time() - t0
            time.sleep(0.3)
            end = position(port, axis)
            print(f"終了 {end:+d}  目標との差 {end - target:+d} 刻み（{(end - target) * 360 / cpr * 3600:+.1f}″）  "
                  f"{done:.2f} 秒  最高 約 {peak:.2f}°/秒")
        finally:
            stop_all(port)


if __name__ == "__main__":
    main()
