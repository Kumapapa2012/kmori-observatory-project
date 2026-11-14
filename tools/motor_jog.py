"""PC Direct でモーター基板に直接速度を指定して、少しだけ動かす試験。

低速（追尾モード）の定速で動かし、時間か移動量の上限で止める。止めたあと、止まるまでに進んだ量も表示する。
何があっても最後に両軸へ停止（:K、だめなら :L）を送る。

    python3 tools/motor_jog.py --axis 1 --dir + --rate 0.1 --seconds 5
"""
import argparse
import glob
import sys
import time

import serial

from probe_motor import ask, le24, CENTER

MAX_RATE = 0.5  # 度/秒（低速）
MAX_RATE_HIGH = 3.0  # 度/秒（高速）
MAX_SECONDS = 20.0
MAX_DEG = 5.0


def hex24(value):
    return f"{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


def value(reply):
    if not reply.startswith("="):
        raise RuntimeError(f"返事がおかしい: {reply!r}")
    return reply[1:].strip()


def cmd(port, c, axis, data=""):
    return value(ask(port, c, f"{axis}{data}"))


def position(port, axis):
    return le24(cmd(port, "j", axis)) - CENTER


def running(port, axis):
    return bool(int(cmd(port, "f", axis)[1], 16) & 1)


def stop_all(port):
    for axis in ("1", "2"):
        try:
            cmd(port, "K", axis)
        except Exception as e:
            print(f"軸 {axis} の :K に失敗: {e}")
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            if not running(port, "1") and not running(port, "2"):
                return
        except Exception:
            pass
        time.sleep(0.1)
    print("止まらないので :L（即停止）を送る")
    for axis in ("1", "2"):
        try:
            cmd(port, "L", axis)
        except Exception as e:
            print(f"軸 {axis} の :L に失敗: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=["1", "2"], required=True)
    ap.add_argument("--dir", choices=["+", "-"], required=True)
    ap.add_argument("--rate", type=float, required=True, help="度/秒")
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--max-deg", type=float, default=2.0)
    ap.add_argument("--high", action="store_true", help="高速モード（:G 3x、間隔は高速倍率をかける）")
    ap.add_argument("--port")
    args = ap.parse_args()
    limit = MAX_RATE_HIGH if args.high else MAX_RATE
    if not 0 < args.rate <= limit:
        sys.exit(f"速度は 0〜{limit} 度/秒")
    if not 0 < args.seconds <= MAX_SECONDS:
        sys.exit(f"時間は 0〜{MAX_SECONDS} 秒")
    if not 0 < args.max_deg <= MAX_DEG:
        sys.exit(f"移動量の上限は 0〜{MAX_DEG} 度")
    name = args.port or glob.glob("/dev/serial/by-id/*Serial*")[0]
    axis = args.axis
    with serial.Serial(name, 9600, timeout=1.0) as port:
        time.sleep(0.2)
        try:
            cpr = le24(cmd(port, "a", axis))
            freq = le24(cmd(port, "b", "1"))
            steps_per_s = args.rate * cpr / 360.0
            ratio = int(cmd(port, "g", axis), 16) if args.high else 1
            period = round(freq * ratio / steps_per_s)
            if period < 10:
                sys.exit(f"間隔 {period} は短すぎる")
            if running(port, axis):
                sys.exit("その軸はすでに動いている")
            start = position(port, axis)
            print(f"CPR {cpr}  タイマー {freq}  倍率 {ratio}  {steps_per_s:.1f} 刻み/秒  間隔 {period}  開始位置 {start:+d}")
            cmd(port, "G", axis, ("3" if args.high else "1") + ("0" if args.dir == "+" else "1"))  # 低速の定速、向き
            cmd(port, "I", axis, hex24(period))
            t0 = time.time()
            cmd(port, "J", axis)
            reason = "時間"
            while True:
                elapsed = time.time() - t0
                moved = (position(port, axis) - start) * 360.0 / cpr
                print(f"{elapsed:5.2f} 秒  {moved:+.4f}°", flush=True)
                if abs(moved) >= args.max_deg:
                    reason = "移動量の上限"
                    break
                if elapsed >= args.seconds:
                    break
                time.sleep(0.2)
            at_stop = position(port, axis)
            cmd(port, "K", axis)
            t1 = time.time()
            while running(port, axis):
                if time.time() - t1 > 3.0:
                    raise RuntimeError("3 秒たっても止まらない")
                time.sleep(0.05)
            end = position(port, axis)
            print(f"止めた理由: {reason}")
            print(f"停止命令までの移動 {(at_stop - start) * 360 / cpr:+.4f}°  "
                  f"停止後に進んだ量 {(end - at_stop) * 360 / cpr * 3600:+.1f}″ ({time.time() - t1:.2f} 秒)  "
                  f"合計 {(end - start) * 360 / cpr:+.4f}°（{end - start:+d} 刻み、{time.time() - t0:.2f} 秒）")
        finally:
            stop_all(port)


if __name__ == "__main__":
    main()
