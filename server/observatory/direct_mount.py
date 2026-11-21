"""直結版の架台。SynScan を通さず、モーター基板の命令で動かす（計画書「段階 2 の決定」）。

外向きの使い方（drive、track、update_track、stop、status、close など）は mount.Mount にそろえ、
サーバー（app.py）からは同じように扱えるようにする。SynScan 固有の機能（本体のアライメント、
本体の追尾、`r` の導入）はないので、それぞれ「ない」と答える。

- 位置は基板の刻み数をそのまま軸の角度（電源投入時の向きが 0、方位 + が右回り、高度 + が上）にする。
  2026-11-14 の実測で、裏返りも飛びもなく、角度は刻み数どおりだった。
- 十字キーは定速の移動（:G 1x/3x と :I）。命令が hold_timeout 途切れたらホストが止める。
  目標移動（:H）は速さを指定できない（低速で 1° に 2.75 秒、高速で約 1.15 秒の固定）ので、導入にだけ使う。
- 安全装置は safety.py（範囲、制限モード、見張り）。基準（Reference）が決まるまでは制限モード。
- 歯車のガタは軸ごとの隙間（gap）として追い、向きを変えて隙間が残るときは毎秒 0.3° で詰めてから
  指定の速さにする。導入の最後は + 向きから近づける。
"""
import threading
import time

from .motor import GOTO_FAST, GOTO_SLOW, SLEW_FAST, SLEW_SLOW, MotorBoard, MotorError
from .mount import MountError
from .safety import AXES, Envelope, Monitor, Reference, SafetyConfig, SafetyError

EXPECTED_CPR = 865050
# 十字キーの速度（1〜9）ごとの速さ（度/秒）。1〜6 はコントローラー版の実測に合わせ、7〜9 は直結の実測の範囲
DEFAULT_SPEEDS = {1: 0.0018, 2: 0.0083, 3: 0.036, 4: 0.0722, 5: 0.146, 6: 0.292, 7: 0.6, 8: 1.2, 9: 2.4}
SLOW_LIMIT = 0.3  # これ以下は低速の定速移動（:G 1x）。0.4 の指定は 0.33 までしか出なかった（2026-11-14）
TAKE_UP_RATE = 0.3  # 隙間を詰めるときの速さ（度/秒）
BRAKE_STEPS = {GOTO_FAST: 3500, GOTO_SLOW: 200}  # INDI の値。実機で 1〜5° の導入が約 10″ 手前に止まった
GOTO_FAST_MIN = 0.5  # これより大きい導入の区間は高速の目標移動
GOTO_APPROACH = 0.3  # 導入の最後に + 向きから近づける量（ガタに足す、度）
STOP_WAIT = 0.5  # :K のあと、止まるのを待つ時間（秒）。過ぎたら :L


class DirectMount:
    def __init__(self, port, cfg=None, board=None, reference=None, poll_interval=0.2, hold_timeout=1.0):
        cfg = cfg or {}
        self.safety = SafetyConfig.from_dict(cfg.get("safety"))
        self.envelope = Envelope(self.safety, reference)
        self.monitor = Monitor(self.safety)
        self.speeds = dict(DEFAULT_SPEEDS)
        self.speeds.update({int(k): float(v) for k, v in (cfg.get("speeds") or {}).items()})
        self.max_rate = max(self.speeds)
        backlash = cfg.get("backlash") or {}
        self.backlash = {a: float(backlash.get(a, {"az": 0.5, "alt": 0.15}[a])) for a in AXES} \
            if backlash.get("enabled", True) else None
        self.poll_interval = poll_interval
        self.hold_timeout = hold_timeout
        self.board = board or MotorBoard(port)
        self.serial = self.board  # app.py は mount.serial.port でポートの有無を確かめる
        self.state_lock = threading.Lock()
        self.moves = {}  # axis -> {"direction", "rate", "speed", "deadline", "stroke", "travel", "taking_up"}
        self.track_rates = {}  # axis -> 秒角/秒
        self.latched = {}
        self.goto = None
        self.goto_result = None
        self.message = ""
        self.error = ""
        self.fault = ""  # 見張りが止めた理由。stop を呼び直すまで残す
        self.closing = False
        self.last_direction = {a: 0 for a in AXES}
        self.gap = {a: self.backlash[a] / 2 for a in AXES} if self.backlash else {}
        try:
            self._check_board(cfg.get("expected_cpr", EXPECTED_CPR))
            self.positions = self._read_positions()
            self.last_status = {a: self.board.status(a) for a in AXES}
        except Exception:
            self.board.close()
            raise
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    # 接続時の確認
    def _check_board(self, expected_cpr):
        self.version, self.mount_code = self.board.version()
        self.k = {}
        for axis in AXES:
            cpr = self.board.cpr(axis)
            if expected_cpr and cpr != expected_cpr:
                raise MountError(f"{axis} の刻み数が {cpr}（期待は {expected_cpr}）。別の架台の可能性があるので接続しません")
            self.k[axis] = cpr / 360.0
        self.freq = self.board.timer_freq()
        self.ratio = {a: self.board.high_ratio(a) for a in AXES}
        status = {a: self.board.status(a) for a in AXES}
        # 電源を入れた直後の基板は未初期化（ハンドコントローラーなしの直結）。初期化だけして動かさない
        self.fresh_power_on = not all(s["initialized"] for s in status.values())
        for axis in AXES:
            if status[axis]["running"]:
                self._stop_board_axis(axis)
            if not status[axis]["initialized"]:
                self.board.initialize(axis)
        print(f"direct mount: board {self.version} code 0x{self.mount_code:02X} freq {self.freq} "
              f"fresh_power_on={self.fresh_power_on}", flush=True)

    def _read_positions(self):
        return {a: self.board.position(a) / self.k[a] for a in AXES}

    # SynScan 固有の機能（直結版にはない）
    def synscan_aligned(self):
        return False

    def tracking_mode(self):
        return "off"

    def set_tracking_mode(self, mode):
        if mode != "off":
            raise MountError("直結版には SynScan 本体の追尾はありません")

    def clock(self):
        # 電源の入れ直しは基板の未初期化で分かるので、時計の比較は使わない（常に有効）
        return time.time()

    def start_goto(self, ra_hours, dec_degrees, plan):
        raise MountError("直結版の導入は goto_axes を使います")

    # 基準
    def set_reference(self, reference):
        with self.state_lock:
            self.envelope.reference = reference or Reference()
        print(f"reference -> {reference}", flush=True)

    @property
    def reference(self):
        return self.envelope.reference

    # 動かす命令（基板）
    def _period(self, axis, speed, fast):
        steps = speed * self.k[axis]
        return round(self.freq * (self.ratio[axis] if fast else 1) / steps)

    def _start_slew(self, axis, direction, speed):
        """止まっている軸を定速で動かし始める。"""
        fast = speed > SLOW_LIMIT
        self.board.set_motion(axis, SLEW_FAST if fast else SLEW_SLOW, direction > 0)
        self.board.set_period(axis, self._period(axis, speed, fast))
        self.board.start(axis)

    def _change_speed(self, axis, speed, fast):
        self.board.set_period(axis, self._period(axis, speed, fast))

    def _stop_board_axis(self, axis):
        self.board.stop(axis)
        deadline = time.monotonic() + STOP_WAIT
        while time.monotonic() < deadline:
            if not self.board.status(axis)["running"]:
                return
            time.sleep(0.03)
        print(f"{axis}: :K で止まらないので :L", flush=True)
        self.board.instant_stop(axis)

    def _remaining_gap(self, axis, direction):
        if not self.backlash:
            return 0.0
        return self.backlash[axis] - self.gap[axis] if direction > 0 else self.gap[axis]

    # 十字キー
    def speed(self, rate):
        return min(self.speeds.get(rate, max(self.speeds.values())), self.envelope.max_rate())

    def move(self, axis, direction, rate, start=True):
        if axis not in AXES or direction not in (1, -1):
            raise ValueError("invalid axis or direction")
        if not 1 <= rate <= self.max_rate:
            raise ValueError(f"rate must be 1..{self.max_rate}")
        now = time.monotonic()
        with self.state_lock:
            if self.fault:
                raise MountError(f"見張りが止めました（{self.fault}）。停止ボタンで解除してください")
            if self.goto:
                raise MountError("導入中です。止めるときは停止ボタンを押してください")
            latch = self.latched.get(axis)
            if latch and latch["direction"] == direction:
                if now - latch["time"] <= self.hold_timeout:
                    latch["time"] = now
                    raise MountError(f"{axis}: 止めた向きです。スティックを離してから操作してください")
                del self.latched[axis]
            if self.envelope.room(axis, self.positions[axis], direction) <= 0:
                raise SafetyError(f"{axis}: 範囲の端です")
            current = self.moves.get(axis)
            if current and current["direction"] == direction and current["rate"] == rate:
                current["deadline"] = now + self.hold_timeout
                return
            if not start:
                return
            speed = self.speed(rate)
            carry = current if current and current["direction"] == direction else None
            taking_up = speed < TAKE_UP_RATE and self._remaining_gap(axis, direction) > 0.02
            actual = TAKE_UP_RATE if taking_up else speed
            same_mode = carry and (carry["actual"] > SLOW_LIMIT) == (actual > SLOW_LIMIT)
            # 追尾の速さは残し、離したとき（_stop_axis）に追尾へ戻す。動かしている間は update_track も
            # その軸を動かさない
        print(f"start {axis} dir={direction} rate={rate} speed={speed} actual={actual} at {self.positions[axis]:+.4f}", flush=True)
        if same_mode:
            self._change_speed(axis, actual, actual > SLOW_LIMIT)
        else:
            if current or self.board.status(axis)["running"]:
                self._stop_board_axis(axis)
            self._start_slew(axis, direction, actual)
        with self.state_lock:
            self.moves[axis] = {"direction": direction, "rate": rate, "speed": speed, "actual": actual,
                                "taking_up": taking_up, "deadline": now + self.hold_timeout,
                                "stroke": carry["stroke"] if carry else now,
                                "travel": carry["travel"] if carry else 0.0}
            self.last_direction[axis] = direction
            self.message = ""

    def drive(self, az, alt):
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
                    moving = axis in self.moves
                if moving:
                    self._stop_axis(axis, "停止命令")
        if failure:
            raise failure

    # 追尾（秒角/秒）
    def track(self, rates):
        with self.state_lock:
            if self.goto:
                raise MountError("導入中は追尾を始められません")
            if self.fault:
                raise MountError(f"見張りが止めました（{self.fault}）")
        for axis, rate in rates.items():
            self._set_track(axis, rate, restart=True)

    def update_track(self, rates):
        for axis, rate in rates.items():
            with self.state_lock:
                if axis not in self.track_rates or axis in self.moves:
                    if axis in self.track_rates:
                        self.track_rates[axis] = rate
                    continue
            self._set_track(axis, rate, restart=False)

    def _set_track(self, axis, rate, restart):
        speed = abs(rate) / 3600.0
        if speed > self.safety.track_max_rate:
            raise SafetyError(f"{axis}: 追尾の速さ {speed:.3f}°/秒 は上限 {self.safety.track_max_rate}°/秒 を超えます")
        direction = 1 if rate >= 0 else -1
        with self.state_lock:
            previous = self.track_rates.get(axis)
            self.track_rates[axis] = rate
        flipped = previous is None or (previous >= 0) != (rate >= 0)
        if speed < 1e-6:
            self._stop_board_axis(axis)
        elif restart or flipped or not self.board.status(axis)["running"]:
            if self.board.status(axis)["running"]:
                self._stop_board_axis(axis)
            self._start_slew(axis, direction, speed)
            self.last_direction[axis] = direction
        else:
            self._change_speed(axis, speed, False)

    # 導入（軸の角度で目標を渡す）
    def goto_axes(self, targets, label="目標"):
        """targets は軸ごとの目標（軸の角度）。各軸 45° 以内、範囲の内側。最後は + 向きから近づける。"""
        with self.state_lock:
            if self.moves or self.goto or self.track_rates:
                raise MountError("移動中や追尾中は導入を始められません")
            if self.fault:
                raise MountError(f"見張りが止めました（{self.fault}）")
            start = dict(self.positions)
        legs = []
        for axis, target in targets.items():
            self.envelope.check_target(axis, target)
            delta = target - start[axis]
            if abs(delta) > self.safety.max_move_deg:
                raise SafetyError(f"{axis}: {delta:+.1f}° は 1 回の上限 {self.safety.max_move_deg:.0f}° を超えます")
            approach = (self.backlash[axis] if self.backlash else 0.0) + GOTO_APPROACH
            if delta < 0 or self.last_direction[axis] < 0:
                pre = target - approach
                self.envelope.check_target(axis, pre)
                legs.append((axis, pre))
            legs.append((axis, target))
        plan_time = sum(abs(b - a) for a, b in self._leg_spans(start, legs)) / 0.5 + 3 * len(legs)
        timeout = plan_time * 1.5 + 5
        now = time.monotonic()
        with self.state_lock:
            self.goto = {"label": label, "legs": legs, "index": -1, "started": now, "deadline": now + timeout,
                         "targets": dict(targets), "leg_started": None, "still_since": None}
            self.goto_result = None
            self.message = f"{label}へ導入中"
        print(f"goto {label} targets={targets} legs={legs} timeout={timeout:.0f}s from {start}", flush=True)
        self._next_leg()

    @staticmethod
    def _leg_spans(start, legs):
        pos = dict(start)
        for axis, target in legs:
            yield pos[axis], target
            pos[axis] = target

    def _next_leg(self):
        with self.state_lock:
            goto = self.goto
            if goto is None:
                return
            goto["index"] += 1
            if goto["index"] >= len(goto["legs"]):
                self.goto = None
                self.goto_result = {"ok": True, "message": f"{goto['label']}へ導入しました", "label": goto["label"]}
                self.message = self.goto_result["message"]
                print(f"goto done at {self.positions}", flush=True)
                return
            axis, target = goto["legs"][goto["index"]]
            delta = target - self.positions[axis]
            goto["leg_started"] = time.monotonic()
            goto["still_since"] = None
        steps = round(abs(delta) * self.k[axis])
        if steps < 2:
            self._next_leg()
            return
        mode = GOTO_FAST if abs(delta) >= GOTO_FAST_MIN else GOTO_SLOW
        self.board.set_motion(axis, mode, delta > 0)
        self.board.set_goto_increment(axis, steps)
        self.board.set_brake_increment(axis, BRAKE_STEPS[mode])
        self.board.start(axis)
        self.last_direction[axis] = 1 if delta > 0 else -1

    def _check_goto(self, status, now):
        with self.state_lock:
            goto = self.goto
        if goto is None:
            return None
        if now > goto["deadline"]:
            return "導入が時間内に終わらなかったため"
        axis, _ = goto["legs"][goto["index"]]
        if now - goto["leg_started"] < 0.3 or status[axis]["running"]:
            goto["still_since"] = None
            return None
        if goto["still_since"] is None:
            goto["still_since"] = now
        elif now - goto["still_since"] >= 0.4:
            self._next_leg()
        return None

    # 止める
    def stop(self, reason="停止命令"):
        with self.state_lock:
            self.moves.clear()
            self.track_rates.clear()
            goto, self.goto = self.goto, None
            if goto:
                self.goto_result = {"ok": False, "message": f"導入を中止: {reason}", "label": goto["label"]}
            self.message = reason
            # 停止ボタンは見張りの停止の解除も兼ねる（理由はログと画面に残る）
            cleared = reason == "停止命令" and bool(self.fault)
            if cleared:
                print(f"fault cleared by stop: {self.fault}", flush=True)
                self.fault = ""
        print(f"stop ({reason}) at {self.positions}", flush=True)
        failures = []
        now = time.monotonic()
        for axis in AXES:
            try:
                self._stop_board_axis(axis)
            except MountError as e:
                try:
                    self.board.instant_stop(axis)
                except MountError:
                    failures.append(f"{axis}: {e}")
            self.monitor.mark_stopped(axis, now)
        if cleared:
            # 未初期化に戻っていたら初期化し直す（位置はそのまま。基準は制限モードのまま）
            for axis in AXES:
                try:
                    if not self.board.status(axis)["initialized"]:
                        self.board.initialize(axis)
                        print(f"{axis}: re-initialized", flush=True)
                except MountError as e:
                    failures.append(f"{axis} init: {e}")
            self.monitor.last = None
        if failures:
            self.error = "stop failed: " + "; ".join(failures)
            raise MountError(self.error)

    def _stop_axis(self, axis, reason):
        with self.state_lock:
            self.moves.pop(axis, None)
            self.message = reason
            rate = self.track_rates.get(axis)
        print(f"stop {axis} ({reason}) at {self.positions[axis]:+.4f}", flush=True)
        self._stop_board_axis(axis)
        self.monitor.mark_stopped(axis, time.monotonic())
        if rate is not None:
            self._set_track(axis, rate, restart=True)

    def _fail(self, reason):
        with self.state_lock:
            self.fault = reason
        print(f"safety stop: {reason}", flush=True)
        try:
            self.stop(f"見張りが停止: {reason}")
        except MountError:
            pass

    # 見張り
    def _commanded(self):
        with self.state_lock:
            out = {a: 0.0 for a in AXES}
            for axis, m in self.moves.items():
                out[axis] = max(m["actual"], m["speed"])
            for axis, rate in self.track_rates.items():
                out[axis] = max(out[axis], abs(rate) / 3600.0)
            if self.goto and self.goto["index"] >= 0:
                axis = self.goto["legs"][self.goto["index"]][0]
                out[axis] = self.safety.jump_speed
        return out

    def _watch(self):
        while not self.closing:
            time.sleep(self.poll_interval)
            try:
                self._tick()
                self.error = ""
            except Exception as e:  # 見張りのスレッドは何があっても止めない
                self.error = str(e) or type(e).__name__
                reason = self.monitor.read_failed()
                if reason:
                    self._fail(reason)

    def _tick(self):
        now = time.monotonic()
        with self.state_lock:
            expired = [a for a, m in self.moves.items() if now > m["deadline"]]
        for axis in expired:
            self._stop_axis(axis, f"{axis}: 操作が途切れたため停止")
        commanded = self._commanded()
        positions = self._read_positions()
        status = {a: self.board.status(a) for a in AXES}
        with self.state_lock:
            previous = self.positions
            self.positions = positions
            self.last_status = status
        reason = self.monitor.update(positions, status, commanded, now)
        if reason and self.fault:
            return  # すでに止めてある。停止ボタンで解除されるまで同じ理由で止め直さない
        if reason:
            if "未初期化" in reason:
                # 電源の瞬断や他の接続で初期化が外れた。基準は信用できないので制限モードへ戻す
                self.set_reference(None)
            self._fail(reason)
            return
        stop_axes = []
        with self.state_lock:
            for axis in AXES:
                delta = positions[axis] - previous[axis]
                if self.backlash:
                    self.gap[axis] = min(max(self.gap[axis] + delta, 0.0), self.backlash[axis])
                m = self.moves.get(axis)
                if m:
                    m["travel"] += abs(delta)
                    if m["travel"] > self.safety.max_move_deg or now - m["stroke"] > self.safety.max_move_seconds:
                        self.latched[axis] = {"direction": m["direction"], "time": now}
                        stop_axes.append((axis, f"{axis}: 1 回の移動の上限で停止。スティックを離してから続けてください"))
                        continue
                direction = m["direction"] if m else (1 if self.track_rates.get(axis, 0) >= 0 else -1) \
                    if axis in self.track_rates else 0
                if direction:
                    speed = m["actual"] if m else abs(self.track_rates[axis]) / 3600.0
                    margin = speed * (self.poll_interval + 0.15) + 0.01
                    if self.envelope.room(axis, positions[axis], direction) <= margin:
                        self.latched[axis] = {"direction": direction, "time": now}
                        self.track_rates.pop(axis, None)
                        stop_axes.append((axis, f"{axis}: 範囲の端で停止"))
                        continue
                if m and m["taking_up"] and self._remaining_gap(axis, m["direction"]) <= m["actual"] * 0.3:
                    m["taking_up"] = False
                    m["actual"] = m["speed"]
                    stop_axes.append((axis, None))
            if self.goto:
                goto_axis = self.goto["legs"][self.goto["index"]][0]
                lo, hi = self.envelope.axis_range(goto_axis)
                out_of_range = not lo - 0.2 <= positions[goto_axis] <= hi + 0.2
            else:
                out_of_range = False
        for axis, why in stop_axes:
            if why is None:
                m = self.moves.get(axis)
                if m:
                    print(f"take-up done {axis} -> {m['actual']}", flush=True)
                    self._change_speed(axis, m["actual"], m["actual"] > SLOW_LIMIT)
            else:
                self._stop_axis(axis, why)
        if out_of_range:
            self._fail("導入中に範囲の外へ出たため")
            return
        reason = self._check_goto(status, now)
        if reason:
            self.stop(f"導入を止めました: {reason}")

    def status(self):
        with self.state_lock:
            ref = self.envelope.reference
            return {
                "backend": "direct",
                "tracking": dict(self.track_rates),
                "moving": {a: {"direction": m["direction"], "rate": m["rate"], "actual": m["rate"]}
                           for a, m in self.moves.items()},
                "az": self.positions["az"], "alt": self.positions["alt"],
                "raw": dict(self.positions), "alt_read": self.positions["alt"], "reported": dict(self.positions),
                "flipped": False, "jumped": bool(self.fault),
                "limits": {a: self.envelope.axis_range(a) for a in AXES}, "max_rate": self.max_rate,
                "restricted": self.envelope.restricted, "referenced": self.envelope.referenced,
                "reference": {"kind": ref.kind, "label": ref.label,
                              "az_offset": ref.az_offset, "alt_offset": ref.alt_offset},
                "fault": self.fault, "fresh_power_on": self.fresh_power_on,
                "message": self.message, "error": self.error,
                # progress と plan.az_amount は今の画面の表示に合わせた形（区間の番号と数）
                "goto": {"label": self.goto["label"], "legs": len(self.goto["legs"]),
                         "leg": self.goto["index"] + 1, "progress": float(self.goto["index"] + 1),
                         "plan": {"az_amount": float(len(self.goto["legs"]))}} if self.goto else None,
                "goto_result": self.goto_result, "synscan_tracking": False,
            }

    def close(self):
        self.closing = True
        try:
            self.stop("終了")
        finally:
            self.thread.join(timeout=2)
            self.board.close()
