"""モーター基板に問い合わせだけを送り、応答を表示する（架台は動かさない）。

SynScan ハンドコントローラーを PC Direct モードにしてから使う。observatory.service は止めておく。
送るのは読み取りの命令（e, a, b, g, s, j, f）だけで、動かす命令や初期化（F）は送らない。

    python3 tools/probe_motor.py [ポート] [--watch 秒]
"""
import argparse
import glob
import sys
import time

import serial

CENTER = 0x800000
# (命令, 説明, 軸ごとに聞くか)
QUERIES = [
    ("e", "版と機種コード", False),
    ("a", "1 回転あたりの刻み数（CPR）", True),
    ("b", "タイマーの周波数", False),
    ("g", "高速時の倍率", True),
    ("s", "ウォーム 1 回転あたりの刻み数", True),
    ("j", "位置", True),
    ("f", "状態", True),
]


def le24(text):
    """6 桁の 16 進（下位バイトが先）を数値にする。"""
    b = bytes.fromhex(text)
    return b[0] | (b[1] << 8) | (b[2] << 16)


def ask(port, cmd, axis):
    line = f":{cmd}{axis}\r".encode()
    port.reset_input_buffer()
    port.write(line)
    # PC Direct ではハンドコントローラーが送った命令をそのまま折り返すので、それを読み捨てる
    reply = port.read_until(b"\r")
    if reply.endswith(line):
        reply = port.read_until(b"\r")
    time.sleep(0.05)
    return reply.decode("ascii", "replace")


def describe(cmd, axis, reply, cpr):
    if not reply:
        return "応答なし"
    if reply.startswith("!"):
        return f"エラー {reply!r}"
    if not reply.startswith("="):
        return f"想定外 {reply!r}"
    data = reply[1:].strip()
    if cmd == "f":
        if len(data) != 3:
            return f"{data!r}"
        n = [int(c, 16) for c in data]
        return (f"{data}  動作中={bool(n[1] & 1)} 追尾モード={bool(n[0] & 1)} "
                f"逆向き={bool(n[0] & 2)} 高速={bool(n[0] & 4)} 初期化済み={bool(n[2] & 1)}")
    if len(data) != 6:
        return f"{data!r}"
    if cmd == "e":
        version = int(data[0:2], 16), int(data[2:4], 16)
        return f"{data}  版 {version[0]}.{version[1]}（表記は資料で要確認）  機種コード 0x{data[4:6]}"
    value = le24(data)
    if cmd == "j":
        steps = value - CENTER
        deg = f"  = {steps * 360.0 / cpr[axis]:+.4f}°" if cpr.get(axis) else ""
        return f"{data}  0x{value:06X}  中心から {steps:+d} 刻み{deg}"
    return f"{data}  {value}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--watch", type=float, default=0, help="位置と状態を読み続ける秒数")
    args = ap.parse_args()
    name = args.port or next(iter(glob.glob("/dev/serial/by-id/*Serial*")), None)
    if not name:
        sys.exit("シリアルのポートが見つからない")
    print(f"ポート {name}  {args.baud} bps")
    with serial.Serial(name, args.baud, timeout=1.0) as port:
        time.sleep(0.2)
        cpr = {}
        for cmd, label, per_axis in QUERIES:
            for axis in ("1", "2") if per_axis else ("1",):
                reply = ask(port, cmd, axis)
                if cmd == "a" and reply.startswith("=") and len(reply.strip()) == 7:
                    cpr[axis] = le24(reply[1:7])
                print(f":{cmd}{axis}  {label}: {describe(cmd, axis, reply, cpr)}")
        end = time.time() + args.watch
        while time.time() < end:
            parts = []
            for axis in ("1", "2"):
                parts.append(describe("j", axis, ask(port, "j", axis), cpr))
                parts.append(describe("f", axis, ask(port, "f", axis), cpr).split("  ", 1)[-1])
            print(time.strftime("%H:%M:%S"), " | ".join(parts), flush=True)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
