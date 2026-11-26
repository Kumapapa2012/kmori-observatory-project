#!/usr/bin/env python3
"""Pico のサーボを操作するホスト側ツール (pyserial が必要)。

例:
  python3 host.py /dev/ttyACM0 50 500    # 正転 50% を 500ms
  python3 host.py /dev/ttyACM0 -30 1000  # 逆転 30% を 1 秒
  python3 host.py /dev/ttyACM0 0         # 停止
  python3 host.py /dev/ttyACM0 --neutral 1490   # 停止点の補正
"""
import argparse
import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("speed", nargs="?", type=float, help="-100..100 (%%)")
    ap.add_argument("ms", nargs="?", type=int, help="回す時間(ms)。省略時はウォッチドッグで停止")
    ap.add_argument("--neutral", type=int, help="停止点パルス幅(us)")
    ap.add_argument("--range", type=int, dest="rng", help="速度100%%の幅(us)")
    ap.add_argument("--move", type=float, help="指定角度(度)だけ相対移動。負で逆転")
    a = ap.parse_args()

    with serial.Serial(a.port, 115200, timeout=1) as s:
        def send(cmd):
            s.write((cmd + "\n").encode())
            print(">", cmd, "->", s.readline().decode().strip())

        if a.neutral is not None:
            send(f"N {a.neutral}")
        if a.rng is not None:
            send(f"R {a.rng}")
        if a.move is not None:
            send(f"M {a.move:g}")
            print("<", s.readline().decode().strip())  # DONE を待つ
        if a.speed is not None:
            send(f"S {a.speed:g}" + (f" {a.ms}" if a.ms else ""))
            if a.ms:
                print("<", s.readline().decode().strip())  # DONE を待つ


if __name__ == "__main__":
    main()
