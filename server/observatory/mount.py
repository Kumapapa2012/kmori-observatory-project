"""SynScan をシリアルで直接制御する手動移動の部品。

移動は「押している間だけ」を基本にする。呼び出し側が move() を繰り返し呼ばなくなると、
監視スレッドが該当の軸を止める。位置の範囲はアライメントに頼らず、起動時の位置からの
相対角度で制限する。プロセスが強制終了されると停止命令は送れないため、物理的な電源断は残す。

歯車のガタは、軸ごとの隙間の位置（gap、0 から amount まで）として追跡する。向きを変えて
隙間が残っているときは、先に速い速度で隙間を詰めてから指定の速度に戻す。起動直後は歯車が
どちらに寄っているか分からないので、隙間の中央にいるものとして扱う。

SynScan の `z` は、未アライメントでは高度の読み取りの原点が任意で、読み取りが ±90° を越えると
「方位 +180°、高度 180° − 値」の表し方に切り替わる（2026-11-07 にこれで自動導入が暴走した）。
この裏返りは読み取りの時点で戻して連続した角度にし、それ以外の飛びは停止する。起動時は、前回の
接続の終わりに保存した状態（flip_hint）を、架台が同じ位置にあるときだけ引き継ぐ。保存がない、または
架台が動いていたときは裏返っていないものとして扱い、裏返った姿勢なら読み取りの方位は 180° ずれて見える。
高度の位置（範囲制限に使う）は読み取りを使わず、速度と時間で積算する。

1 回の操作（同じ向きに押し続けている間）で動かせる角度と時間には上限があり、上限や飛びで
止めた軸は、スティックを一度離すまで同じ向きに動かせない。

自動導入（goto）は SynScan の `r`（精密な赤経・赤緯）に任せ、SynScan 本体のアライメント済みのときだけ使う。
呼び出し側が示した計画（方位の向きと量、高度の範囲、時間）から外れたら、`M`（取り消し）と両軸の停止を送る。
"""
import calendar
import threading
import time

import serial

AXES = {"az": 16, "alt": 17}
FORWARD, REVERSE = 36, 37  # P コマンドの固定速度移動（正方向、負方向）
TRACK_FORWARD, TRACK_REVERSE = 6, 7  # P コマンドの速度指定（0.25 秒角/秒単位）
# 固定速度ごとの速さ（度/秒）。1〜6 は方位の読み取りでの実測（2026-11-01）、9 は 2026-11-07 の高度の往復での実測。
# 7、8 は未測定で、表の最大値を使う（速めに見積もるので安全側）
DEFAULT_SPEEDS = {1: 0.0018, 2: 0.0083, 3: 0.036, 4: 0.0722, 5: 0.146, 6: 0.292, 9: 2.41}
# 裏返りとみなす、直前の高度（連続した角度）と ±90° との差の上限
POLE_MARGIN = 10.0
# 前回の裏返りの状態を引き継ぐときに、架台が動いていないとみなす読み取りの差（度）
FLIP_HINT_TOLERANCE = 0.5
# 飛びの判定で、読み取りの間隔に比例して許す速さ（度/秒）。速度 9 より速い
JUMP_SPEED = 4.0
# 自動導入の監視。逆向きに回ってよい量、計画より余分に回ってよい量（度）
GOTO_REVERSE_DEG = 5.0
GOTO_EXTRA_DEG = 8.0
GOTO_STILL_DEG = 0.003  # 読み取りの 1 回の間隔でこれ以下なら止まっているとみなす（追尾の速さは約 0.001°）
GOTO_SETTLE = 1.0  # 終わったとみなすまで、止まったままでいる時間（秒）
SYNSCAN_TRACKING = {0: "off", 1: "altaz", 2: "equatorial", 3: "pec"}


class MountError(Exception):
    pass


def _wrap(delta):
    return (delta + 180.0) % 360.0 - 180.0


def _unflip(reported, flipped):
    """裏返った表し方の読み取りを、連続した角度（方位 0〜360、高度 ±180）に戻す。"""
    if not flipped:
        return {"az": reported["az"] % 360.0, "alt": _wrap(reported["alt"])}
    return {"az": (reported["az"] - 180.0) % 360.0, "alt": _wrap(180.0 - reported["alt"])}


class Mount:
    def __init__(self, port, max_rate=6, az_limit=90.0, alt_limit=45.0,
                 hold_timeout=1.0, poll_interval=0.2, backlash=None, speeds=None,
                 max_move_deg=45.0, max_move_seconds=120.0, jump_deg=5.0, alt_start_delay=0.4,
                 flip_hint=None):
        self.max_rate = max_rate
        self.limits = {"az": az_limit, "alt": alt_limit}
        self.hold_timeout = hold_timeout
        self.poll_interval = poll_interval
        self.serial = serial.Serial(port, 9600, timeout=1.0)
        self.io_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.track_rates = {}  # axis -> 秒角/秒。スティックを離すとこの速度に戻る
        self.moves = {}  # axis -> {"direction", "rate", "actual", "deadline", "started", "credited"}
        self.backlash = backlash if backlash and backlash.get("enabled") else None
        self.gap = {a: self.backlash[a]["amount"] / 2 for a in AXES} if self.backlash else {}
        self.speeds = dict(DEFAULT_SPEEDS)
        self.speeds.update({int(k): float(v) for k, v in (speeds or {}).items()})
        self.max_move_deg = max_move_deg
        self.max_move_seconds = max_move_seconds
        self.jump_deg = jump_deg
        self.alt_start_delay = alt_start_delay
        self.last_raw = None  # 裏返りを戻した連続の角度
        self.last_reported = None  # 架台が返した値そのまま
        self.last_read_time = None
        self.flipped = False
        # 前回の接続の終わりに保存した裏返りの状態。架台が同じ位置にあるときだけ引き継ぐ
        self.flip_hint = flip_hint
        self.jumped = False  # 飛びを検出したら、再起動まで位置の記録は信用できない
        self.latched = {}  # axis -> 上限や飛びで止めた向き。スティックを離すまで同じ向きに動かさない
        self.offset = {"az": 0.0, "alt": 0.0}
        self.alt_read = 0.0  # 高度の読み取りでの相対角度（参考。範囲制限には使わない）
        self.last_tick = None
        self.goto = None  # 自動導入の計画と経過。終わると None
        # SynScan 本体が追尾しているか（最後に `t` で読んだ値）。固定速度の `P` で切れる
        self.synscan_tracking = False
        self.goto_result = None  # 直前の自動導入の結果（{"ok", "message"}）
        self.message = ""
        self.error = ""
        self.closing = False
        try:
            time.sleep(0.2)
            self.serial.reset_input_buffer()
            self.stop("起動時の停止")
            self._read_position()
        except Exception:
            self.serial.close()
            raise
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def _exchange(self, command, size):
        with self.io_lock:
            self.serial.reset_input_buffer()
            self.serial.write(command)
            self.serial.flush()
            reply = self.serial.read(size)
        if len(reply) != size or not reply.endswith(b"#"):
            raise MountError(f"unexpected reply to {command!r}: {reply!r}")
        return reply

    def _send_rate(self, axis, direction, rate):
        code = FORWARD if direction > 0 else REVERSE
        self._exchange(bytes([ord("P"), 2, AXES[axis], code, rate, 0, 0, 0]), 1)

    def _send_track(self, axis, rate):
        code = TRACK_FORWARD if rate >= 0 else TRACK_REVERSE
        value = min(round(abs(rate) * 4), 0xFFFF)
        self._exchange(bytes([ord("P"), 3, AXES[axis], code, value >> 8, value & 0xFF, 0, 0]), 1)

    def track(self, rates):
        """秒角/秒で追尾する。歯車の隙間が残る軸は、先に詰めてから追尾の速度に入る。"""
        print(f"track {rates}", flush=True)
        with self.state_lock:
            if self.goto:
                raise MountError("自動導入中は追尾を始められません")
            self.synscan_tracking = False
        for axis, rate in rates.items():
            direction = 1 if rate >= 0 else -1
            with self.state_lock:
                self.track_rates[axis] = rate
                if axis in self.moves:
                    continue
                actual = self._take_up_rate(axis, direction, 0)
                if actual:
                    now = time.monotonic()
                    self.moves[axis] = {"direction": direction, "rate": 0, "actual": actual,
                                        "deadline": float("inf"), "started": now, "track": True}
            if actual:
                self._send_rate(axis, direction, actual)
            else:
                self._send_track(axis, rate)

    def update_track(self, rates):
        """追尾の速度を更新する。スティックや隙間を詰める動作の間は、記録だけ更新する。"""
        for axis, rate in rates.items():
            with self.state_lock:
                if axis not in self.track_rates:
                    continue
                self.track_rates[axis] = rate
                busy = axis in self.moves
            if not busy:
                self._send_track(axis, rate)

    def speed(self, rate):
        return self.speeds.get(rate, max(self.speeds.values()))

    def _read_position(self):
        """位置を読み、裏返りを戻して方位の相対角度を積算する。飛びを見つけたら全軸を止める。"""
        reply = self._exchange(b"z", 18)
        az, alt = (int(v, 16) / 2 ** 32 * 360.0 for v in reply[:-1].decode().split(","))
        reported = {"az": az, "alt": alt}
        now = time.monotonic()
        jump = None
        with self.state_lock:
            if self.last_raw is None:
                hint = self.flip_hint
                if hint and all(abs(_wrap(reported[a] - hint["reported"][a])) <= FLIP_HINT_TOLERANCE for a in AXES):
                    self.flipped = bool(hint["flipped"])
                    print(f"reading flipped={self.flipped} carried over from the last connection", flush=True)
                raw = _unflip(reported, self.flipped)
            else:
                limit = self.jump_deg + JUMP_SPEED * (now - self.last_read_time)

                def deltas(flipped):
                    cont = _unflip(reported, flipped)
                    return cont, {a: _wrap(cont[a] - self.last_raw[a]) for a in AXES}

                raw, delta = deltas(self.flipped)
                if max(abs(d) for d in delta.values()) > limit:
                    other, other_delta = deltas(not self.flipped)
                    near_pole = abs(abs(self.last_raw["alt"]) - 90.0) <= POLE_MARGIN
                    if near_pole and max(abs(d) for d in other_delta.values()) <= limit:
                        self.flipped = not self.flipped
                        raw, delta = other, other_delta
                        print(f"reading flipped={self.flipped} at az={raw['az']:.3f} alt={raw['alt']:.3f}", flush=True)
                    else:
                        jump = delta
                if jump is None:
                    self.offset["az"] += delta["az"]
                    self.alt_read += delta["alt"]
                    if self.goto or (self.synscan_tracking and not self.moves and not self.track_rates):
                        # 自動導入と SynScan の追尾はアライメント済みのときだけなので、
                        # 速度で積算できない間は高度の読み取りで位置を進める
                        self.offset["alt"] += delta["alt"]
                    if self.backlash:
                        for axis in AXES:
                            if self.backlash[axis]["source"] == "encoder":
                                self._advance_gap(axis, delta[axis])
                else:
                    # 位置の記録は進めず、新しい値を基準にする。動いていた軸は離すまで止めておく
                    self.jumped = True
                    for axis, m in self.moves.items():
                        self.latched[axis] = {"direction": m["direction"], "time": now}
            self.last_raw = raw
            self.last_reported = reported
            self.last_read_time = now
        if jump is not None:
            print(f"reading jumped {jump} (reported {reported})", flush=True)
            self.stop(f"読み取りが飛んだため停止（方位 {jump['az']:+.1f}°、高度 {jump['alt']:+.1f}°）")
        return raw

    def _integrate(self, now):
        """高度の位置を速度と時間で積算し、1 回の操作の移動量を数える。止める軸を返す。"""
        over = []
        with self.state_lock:
            dt = 0.0 if self.last_tick is None else now - self.last_tick
            self.last_tick = now
            for axis, m in self.moves.items():
                if now - m["started"] < (self.alt_start_delay if axis == "alt" else 0.0):
                    continue
                step = self.speed(m["actual"]) * dt
                if axis == "alt":
                    self.offset["alt"] += m["direction"] * step
                if m.get("track"):
                    continue
                m["travel"] += step
                if m["travel"] > self.max_move_deg or now - m["stroke"] > self.max_move_seconds:
                    over.append(axis)
                    self.latched[axis] = {"direction": m["direction"], "time": now}
            rate = self.track_rates.get("alt")
            if rate is not None and "alt" not in self.moves:
                self.offset["alt"] += rate / 3600.0 * dt
        return over

    def _advance_gap(self, axis, delta):
        self.gap[axis] = min(max(self.gap[axis] + delta, 0.0), self.backlash[axis]["amount"])

    def _remaining(self, axis, direction):
        return self.backlash[axis]["amount"] - self.gap[axis] if direction > 0 else self.gap[axis]

    def _take_up_rate(self, axis, direction, rate):
        """隙間を詰める間に使う速度を返す。詰める必要がなければ指定の速度のまま。"""
        if not self.backlash:
            return rate
        cfg = self.backlash[axis]
        # 切り替えの遅れで行き過ぎないよう、手前で通常の速度に戻す
        lead = self.backlash["speeds"][str(cfg["rate"])] * cfg["lead"]
        return cfg["rate"] if rate < cfg["rate"] and self._remaining(axis, direction) > lead else rate

    def _update_take_up(self, elapsed):
        """動かした量を反映し、隙間を詰め終えた軸を指定の速度に戻す。"""
        finished = []
        resumed = []
        with self.state_lock:
            now = time.monotonic()
            for axis, m in self.moves.items():
                cfg = self.backlash[axis]
                speeds = self.backlash["speeds"]
                # 未測定の速い速度では、測定済みの最大の値を下限として使う
                speed = speeds.get(str(m["actual"]), max(speeds.values()))
                # 読み取りを使わない軸は、動き出しの遅れの後から速度で積算する
                if cfg["source"] == "time" and speed and now - m["started"] > cfg["start_delay"]:
                    self._advance_gap(axis, m["direction"] * speed * elapsed)
                lead = self.backlash["speeds"][str(cfg["rate"])] * cfg["lead"]
                if m["actual"] != m["rate"] and self._remaining(axis, m["direction"]) <= lead:
                    if m.get("track"):
                        resumed.append(axis)
                    else:
                        m["actual"] = m["rate"]
                        finished.append((axis, m["direction"], m["rate"]))
            rates = {axis: self.track_rates[axis] for axis in resumed if axis in self.track_rates}
            for axis in resumed:
                self.moves.pop(axis, None)
        for axis, rate in rates.items():
            self._send_track(axis, rate)
        for axis, direction, rate in finished:
            print(f"take-up done {axis} dir={direction} rate={rate}", flush=True)
            self._send_rate(axis, direction, rate)

    def synscan_aligned(self):
        """SynScan 本体のアライメントが済んでいるか（`J`）。済むと `z` が本当の方位・高度になる。"""
        return self._exchange(b"J", 2)[0] == 1

    def clock(self):
        """架台の時計を秒で返す。電源投入時の既定値から進むので、絶対時刻としては使わない。"""
        reply = self._exchange(b"h", 9)
        hour, minute, second, month, day, year = reply[:6]
        return calendar.timegm((2000 + year, month, day, hour, minute, second))

    def move(self, axis, direction, rate, start=True):
        """start=False は押し続けの延長で、動いていない軸を動かし始めることはない。"""
        if axis not in AXES or direction not in (1, -1):
            raise ValueError("invalid axis or direction")
        if not 1 <= rate <= self.max_rate:
            raise ValueError(f"rate must be 1..{self.max_rate}")
        with self.state_lock:
            if self.goto:
                raise MountError("自動導入中です。止めるときは停止ボタンを押してください")
            # 固定速度の `P` は SynScan 本体の追尾を切る
            self.synscan_tracking = False
            now = time.monotonic()
            latch = self.latched.get(axis)
            if latch and latch["direction"] == direction:
                # 押し続けている間は止めたまま。命令が途切れていたら、離したものとみなす
                if now - latch["time"] <= self.hold_timeout:
                    latch["time"] = now
                    raise MountError(f"{axis}: 止めた向きです。スティックを離してから操作してください")
                del self.latched[axis]
            if abs(self.offset[axis]) >= self.limits[axis] and self.offset[axis] * direction > 0:
                raise MountError(f"{axis} limit reached")
            current = self.moves.get(axis)
            same = current and current["direction"] == direction and current["rate"] == rate
            if same:
                current["deadline"] = now + self.hold_timeout
                return
            if not start:
                # 停止の後に遅れて届いた延長の命令では再び動かさない
                print(f"ignored late hold {axis} {direction} rate={rate}", flush=True)
                return
            actual = self._take_up_rate(axis, direction, rate)
            # 同じ向きのまま速度だけ変えたときは、1 回の操作として移動量を引き継ぐ
            carry = current if current and current["direction"] == direction and not current.get("track") else None
        print(f"start {axis} dir={direction} rate={rate} actual={actual} at az={self.offset['az']:.4f} alt={self.offset['alt']:.4f}", flush=True)
        self._send_rate(axis, direction, actual)
        with self.state_lock:
            now = time.monotonic()
            self.moves[axis] = {"direction": direction, "rate": rate, "actual": actual,
                                "deadline": now + self.hold_timeout,
                                "started": carry["started"] if carry else now,
                                "stroke": carry["stroke"] if carry else now,
                                "travel": carry["travel"] if carry else 0.0}
            self.message = ""

    def drive(self, az, alt):
        """スティックの状態を反映する。値は符号付きの速度で、0 はその軸の停止。
        片方の軸を動かせなくても、もう片方は反映してから例外を上げる。"""
        failure = None
        for axis, value in (("az", az), ("alt", alt)):
            if value:
                try:
                    self.move(axis, 1 if value > 0 else -1, abs(value))
                except MountError as e:
                    failure = failure or e
            else:
                with self.state_lock:
                    self.latched.pop(axis, None)
                if axis in self.moves:
                    self._stop_axis(axis, "停止命令")
        if failure:
            raise failure

    def tracking_mode(self):
        """SynScan 本体の追尾の状態（`t`）。off / altaz / equatorial / pec。"""
        mode = SYNSCAN_TRACKING.get(self._exchange(b"t", 2)[0], "unknown")
        # 速度指定の `P` で追尾している間も `t` は 1 を返すので、サーバーの追尾中は SynScan の追尾とみなさない
        with self.state_lock:
            self.synscan_tracking = mode not in ("off", "unknown") and not self.track_rates
        return mode

    def set_tracking_mode(self, mode):
        """SynScan 本体の追尾を切り替える（`T`）。サーバーの追尾とは同時に使わない。"""
        code = {v: k for k, v in SYNSCAN_TRACKING.items()}[mode]
        with self.state_lock:
            if code and (self.moves or self.track_rates or self.goto):
                raise MountError("移動中やサーバーの追尾中は SynScan の追尾を使えません")
        print(f"synscan tracking -> {mode}", flush=True)
        self._exchange(b"T" + bytes([code]), 1)
        self.synscan_tracking = bool(code)

    def start_goto(self, ra_hours, dec_degrees, plan):
        """SynScan の自動導入を始める。plan は {"label", "az_direction"（+1/-1）, "az_amount",
        "alt_range"（[下限, 上限]）, "timeout"（秒）}。計画を外れたら _watch が止める。"""
        if not self.synscan_aligned():
            raise MountError("SynScan 本体のアライメントが済んでいないので、自動導入は使えません")
        with self.state_lock:
            if self.moves or self.goto:
                raise MountError("移動中は自動導入を始められません")
            start = dict(self.last_raw)
        # サーバーの追尾や SynScan の追尾を止めてから送る
        self.stop("自動導入の前に停止")
        ra = round(ra_hours % 24 / 24 * 2 ** 24) % 2 ** 24 << 8
        dec = round(dec_degrees % 360 / 360 * 2 ** 24) % 2 ** 24 << 8
        now = time.monotonic()
        with self.state_lock:
            self.goto = {"label": plan["label"], "plan": plan, "start": start, "last": start,
                         "started": now, "deadline": now + plan["timeout"], "progress": 0.0}
            self.goto_result = None
            self.message = f"{plan['label']}へ自動導入中"
        print(f"goto {plan['label']} RA={ra_hours:.5f}h Dec={dec_degrees:.4f} plan={plan} from {start}", flush=True)
        try:
            self._exchange(f"r{ra:08X},{dec:08X}".encode(), 1)
        except (MountError, serial.SerialException, OSError) as e:
            self.stop(f"自動導入の命令に失敗: {e}")
            raise

    def _check_goto(self):
        """自動導入が計画どおりか確かめ、終わったら記録する。止める理由か None を返す。"""
        with self.state_lock:
            goto = self.goto
            raw = self.last_raw
        if goto is None:
            return None
        plan = goto["plan"]
        moved = _wrap(raw["az"] - goto["start"]["az"]) * plan["az_direction"]
        goto["progress"] = moved
        if moved < -GOTO_REVERSE_DEG:
            return f"方位が計画と逆向きに {-moved:.1f}° 回ったため"
        if moved > plan["az_amount"] + GOTO_EXTRA_DEG:
            return f"方位が計画より多く回ったため（{moved:.1f}°）"
        low, high = plan["alt_range"]
        if not low <= raw["alt"] <= high:
            return f"高度が範囲外になったため（{raw['alt']:.1f}°）"
        if time.monotonic() > goto["deadline"]:
            return "時間内に終わらなかったため"
        # `L` は小さな移動の始めに一瞬 0 を返すことがある（2026-11-07 実機）。0 のまま読み取りが
        # GOTO_SETTLE 秒止まっていたら終わったとみなす
        now = time.monotonic()
        moving = max(abs(_wrap(raw[a] - goto["last"][a])) for a in AXES) > GOTO_STILL_DEG
        goto["last"] = raw
        busy = self._exchange(b"L", 2)[:1] != b"0"
        if busy or moving:
            goto["still_since"] = None
            return None
        if goto.get("still_since") is None:
            goto["still_since"] = now
        if now - goto["started"] > 1.0 and now - goto["still_since"] >= GOTO_SETTLE:
            with self.state_lock:
                if self.goto is goto:
                    self.goto = None
                    self.goto_result = {"ok": True, "message": f"{goto['label']}へ導入しました", "label": goto["label"]}
                    self.message = self.goto_result["message"]
            print(f"goto done at {raw}", flush=True)
            # アライメント済みの SynScan は導入の後に自分で追尾を始める
            self.tracking_mode()
        return None

    def stop(self, reason="停止命令"):
        """全軸を止める。片方の軸で失敗しても、もう片方の停止を必ず試みる。"""
        with self.state_lock:
            self.moves.clear()
            tracking = list(self.track_rates)
            self.track_rates.clear()
            self.message = reason
            goto, self.goto = self.goto, None
            if goto:
                self.goto_result = {"ok": False, "message": f"自動導入を中止: {reason}", "label": goto["label"]}
        print(f"stop ({reason}) at az={self.offset['az']:.4f} alt={self.offset['alt']:.4f}", flush=True)
        failures = []
        if goto:
            try:
                self._exchange(b"M", 1)
            except (MountError, serial.SerialException, OSError) as e:
                failures.append(f"cancel goto: {e}")
        for axis in AXES:
            for attempt in range(3):
                try:
                    if axis in tracking:
                        self._send_track(axis, 0)
                    self._send_rate(axis, 1, 0)
                    break
                except (MountError, serial.SerialException, OSError) as e:
                    last = e
            else:
                failures.append(f"{axis}: {last}")
        if failures:
            self.error = "stop failed: " + "; ".join(failures)
            raise MountError(self.error)

    def _stop_axis(self, axis, reason):
        with self.state_lock:
            self.moves.pop(axis, None)
            self.message = reason
        print(f"stop {axis} ({reason}) at az={self.offset['az']:.4f} alt={self.offset['alt']:.4f}", flush=True)
        self._send_rate(axis, 1, 0)
        # 追尾中にスティックを離したら、追尾の速度へ戻る
        rate = self.track_rates.get(axis)
        if rate is not None:
            self._send_track(axis, rate)

    def _watch(self):
        while not self.closing:
            time.sleep(self.poll_interval)
            try:
                with self.state_lock:
                    now = time.monotonic()
                    expired = [a for a, m in self.moves.items() if now > m["deadline"]]
                for axis in expired:
                    self._stop_axis(axis, f"{axis}: 操作が途切れたため停止")
                self._read_position()
                if self.goto:
                    reason = self._check_goto()
                    if reason:
                        self.stop(f"自動導入を止めました: {reason}")
                for axis in self._integrate(time.monotonic()):
                    self._stop_axis(axis, f"{axis}: 1 回の移動の上限で停止。スティックを離してから続けてください")
                if self.backlash:
                    self._update_take_up(self.poll_interval)
                with self.state_lock:
                    over = [a for a, m in self.moves.items()
                            if abs(self.offset[a]) >= self.limits[a]
                            and self.offset[a] * m["direction"] > 0]
                    over += [a for a, r in self.track_rates.items()
                             if a not in over and abs(self.offset[a]) >= self.limits[a]
                             and self.offset[a] * r > 0]
                    goto_over = self.goto and any(abs(self.offset[a]) >= self.limits[a] for a in AXES)
                if goto_over:
                    self.stop("自動導入を止めました: 範囲の上限に達したため")
                for axis in over:
                    with self.state_lock:
                        self.track_rates.pop(axis, None)
                    self._stop_axis(axis, f"{axis}: 範囲の上限で停止")
                self.error = ""
            except (MountError, serial.SerialException, OSError) as e:
                self.error = str(e)
                try:
                    self.stop("通信エラーのため停止")
                except (MountError, serial.SerialException, OSError):
                    pass

    def status(self):
        with self.state_lock:
            return {
                "tracking": dict(self.track_rates),
                "moving": {a: {"direction": m["direction"], "rate": m["rate"], "actual": m["actual"]}
                           for a, m in self.moves.items()},
                "az": self.offset["az"], "alt": self.offset["alt"], "raw": self.last_raw,
                "alt_read": self.alt_read, "reported": self.last_reported,
                "flipped": self.flipped, "jumped": self.jumped,
                "limits": self.limits, "max_rate": self.max_rate,
                "message": self.message, "error": self.error,
                "goto": {"label": self.goto["label"], "plan": self.goto["plan"],
                         "progress": self.goto["progress"]} if self.goto else None,
                "goto_result": self.goto_result, "synscan_tracking": self.synscan_tracking,
            }

    def close(self):
        self.closing = True
        try:
            self.stop("終了")
        finally:
            self.thread.join(timeout=2)
            self.serial.close()
