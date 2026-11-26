# Raspberry Pi Pico (MicroPython) - FS90R 連続回転サーボ制御
# USB シリアル (CDC) 経由で 1 行コマンドを受け取る。
#
#   S <速度>        速度 -100..100 (%)。正=正転、負=逆転、0=停止
#   S <速度> <ms>   指定時間だけ回して自動停止
#   X               停止
#   M <度>          指定角度だけ相対移動 (正=正転、負=逆転)。速度 MOVE_FWD /
#                   MOVE_REV でパルス時間 = |度| / deg_per_ms だけ回す (開ループ)
#   K <度/ms>       正転の換算係数 deg_per_ms の補正 (既定 0.3)
#   KR <度/ms>      逆転の換算係数の補正 (既定 0.29)
#   N <us>          停止点(中立)パルス幅の補正 (既定 1500)
#   R <us>          速度100%に相当する中立からの幅 (既定 300)
#   ?               現在値を表示
#
# 応答は "OK ..." または "ERR ..."。
# 安全のため、速度指定のみ(時間なし)の場合でも WATCHDOG_MS 間コマンドが
# 来なければ自動停止する。回し続けたいときはホストから定期的に S を送ること。

import sys
import select
from time import ticks_ms, ticks_diff
from machine import Pin, PWM

SERVO_PIN = 15
WATCHDOG_MS = 2000
# M コマンドで使う速度 (%)。応答は回り始め付近で急に立ち上がり、その先は
# ほぼ一定 (約 0.3 度/ms) になる。立ち上がりの途中を避け、一定の領域を使う。
# 正転は 8 (1564us)、逆転は 14.5 (1384us)。中立 1500、range 800 のとき。
MOVE_FWD = 8
MOVE_REV = 14.5
deg_per_ms = 0.3     # 実測: 20/50/100ms で 6/15/30 度 (目測、要再測定)
deg_per_ms_rev = 0.29  # 逆転用。10 往復で正転側に 30 度ずれた (3.3%) ため補正

neutral_us = 1500
range_us = 800   # データシートの全幅。速度 1% = 8us、速度 8 で約 17rpm（実測）

pwm = PWM(Pin(SERVO_PIN))
pwm.freq(50)

speed = 0
stop_at = None       # 時間指定の終了時刻 (ticks_ms)
last_cmd = ticks_ms()


def apply(pct):
    global speed
    speed = max(-100, min(100, pct))
    if speed == 0:
        # 停止時はパルス自体を止める。FS90R は信号がないと止まるので、
        # 中立点のずれや温度・電圧による這い回りが起きない。
        pwm.duty_u16(0)
        return
    us = neutral_us + range_us * speed / 100
    pwm.duty_u16(int(us / 20000 * 65535))


def handle(line):
    global neutral_us, range_us, stop_at, last_cmd, deg_per_ms, deg_per_ms_rev
    parts = line.split()
    if not parts:
        return
    cmd = parts[0].upper()
    last_cmd = ticks_ms()
    try:
        if cmd == "S":
            apply(float(parts[1]))
            stop_at = None
            if len(parts) > 2:
                stop_at = (ticks_ms() + int(parts[2])) & 0x3FFFFFFF
            print("OK S", speed)
        elif cmd == "M":
            deg = float(parts[1])
            k = deg_per_ms if deg > 0 else deg_per_ms_rev
            ms = int(abs(deg) / k + 0.5)  # 四捨五入 (float32 での切り捨て誤差を避ける)
            if ms > 20000:
                raise ValueError
            if ms > 0:
                apply(MOVE_FWD if deg > 0 else -MOVE_REV)
                stop_at = (ticks_ms() + ms) & 0x3FFFFFFF
            print("OK M", deg, ms)
        elif cmd == "K":
            deg_per_ms = float(parts[1])
            if deg_per_ms <= 0:
                raise ValueError
            print("OK K", deg_per_ms)
        elif cmd == "KR":
            deg_per_ms_rev = float(parts[1])
            if deg_per_ms_rev <= 0:
                raise ValueError
            print("OK KR", deg_per_ms_rev)
        elif cmd == "X":
            apply(0)
            stop_at = None
            print("OK X")
        elif cmd == "N":
            neutral_us = int(parts[1])
            apply(speed)
            print("OK N", neutral_us)
        elif cmd == "R":
            range_us = int(parts[1])
            apply(speed)
            print("OK R", range_us)
        elif cmd == "?":
            print("OK speed=%s neutral=%d range=%d k=%s kr=%s" % (speed, neutral_us, range_us, deg_per_ms, deg_per_ms_rev))
        else:
            print("ERR unknown", cmd)
    except (IndexError, ValueError):
        print("ERR bad args")


poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
buf = ""
apply(0)

while True:
    if poll.poll(1):  # 停止時刻の判定を 1ms 単位にする（短いパルスの精度）
        ch = sys.stdin.read(1)
        if ch in ("\n", "\r"):
            handle(buf)
            buf = ""
        else:
            buf += ch
            if len(buf) > 64:
                buf = ""

    now = ticks_ms()
    if speed != 0:
        if stop_at is not None:
            if ticks_diff(now, stop_at) >= 0:
                apply(0)
                stop_at = None
                print("DONE")
        elif ticks_diff(now, last_cmd) > WATCHDOG_MS:
            apply(0)
            print("WATCHDOG")
