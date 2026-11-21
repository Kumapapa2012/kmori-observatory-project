"""ファインダーのプレートソルブ（ASTAP）と、それを使う自動アラインメント。

手順は計画書の「アライメントの手順（案、2026年11月21日）」。見えている空の範囲（方位 10° ごとの
可否と高度の下限）の中で高度 30〜50°（設定の alt_band）の点へ動かし、ファインダーの 1 コマを ASTAP で解いて、
軸の角度と本当の方位・高度の組を集める。方位で離れた 3 点から向きのずれと傾きを求め
（alignment.fit）、各点の残りの誤差が許容範囲に入れば保存する。解けない点は方位を変えて替える。
"""
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import alignment as alignment_model

SKY_BINS = 36  # 方位 10° ごと
DEFAULT_SKY_MASK = {"bins": [True] * SKY_BINS, "min_alt": 20.0}


def check_sky_mask(body):
    try:
        bins = [bool(b) for b in body["bins"]]
        min_alt = float(body.get("min_alt", 20.0))
    except (KeyError, TypeError, ValueError):
        raise ValueError("bins（36 個の真偽）と min_alt を指定してください")
    if len(bins) != SKY_BINS:
        raise ValueError(f"bins は {SKY_BINS} 個です")
    if not math.isfinite(min_alt) or not 0 <= min_alt <= 70:
        raise ValueError("高度の下限は 0〜70° です")
    if not any(bins):
        raise ValueError("見えている方位がありません")
    return {"bins": bins, "min_alt": min_alt}


def visible(mask, az):
    return mask["bins"][int(alignment_model.wrap360(az) // (360 / SKY_BINS)) % SKY_BINS]


class Solver:
    """ASTAP の CLI で 1 枚を解く。結果は J2000 の視野の中心（赤経 時、赤緯 度）。"""

    def __init__(self, cfg):
        self.astap = cfg.get("astap", "astap_cli")
        self.database_dir = cfg.get("database_dir", "/opt/astap")
        self.database = cfg.get("database", "w08")
        self.fov = float(cfg.get("fov_height", 13.3))  # 切り抜いたあとの画像の高さの視野（度）
        self.timeout = float(cfg.get("timeout", 60))

    def available(self):
        return shutil.which(self.astap) is not None

    def solve(self, image, hint=None, radius=None, point=None, cancel=None):
        """hint は (赤経 時, 赤緯 度)。point は向きとして返す画素（左上原点の (列, 行)）で、None なら中心。
        解けなければ None。"""
        image = Path(image)
        args = [self.astap, "-f", str(image), "-d", self.database_dir, "-D", self.database, "-fov", f"{self.fov:.2f}"]
        if hint:
            args += ["-ra", f"{hint[0]:.4f}", "-spd", f"{hint[1] + 90:.4f}", "-r", f"{radius or 10:.0f}"]
        else:
            args += ["-r", "180"]
        ini = image.with_suffix(".ini")
        try:
            ini.unlink()
        except FileNotFoundError:
            pass
        started = time.monotonic()
        # 中止（cancel の Event）に早く応えるよう、終わるのを少しずつ待つ
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if (cancel is not None and cancel.is_set()) or time.monotonic() - started > self.timeout:
                    proc.kill()
                    proc.wait()
                    return None
        values = parse_ini(ini)
        if values.get("PLTSOLVD") != "T":
            return None
        ra, dec = float(values["CRVAL1"]), float(values["CRVAL2"])
        if point is not None:
            ra, dec = pixel_to_radec(values, point[0], point[1])
        return {"ra_hours": ra / 15.0, "dec": dec,
                "scale": abs(float(values.get("CDELT2", 0.0))) * 3600.0, "rotation": float(values.get("CROTA2", 0.0)),
                "seconds": time.monotonic() - started}


def parse_ini(path):
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.split("/")[0].strip()
    return values


def pixel_to_radec(values, col, row):
    """ASTAP の解（.ini の CRPIX、CRVAL、CD）で、画素（左上原点の列と行）の赤経・赤緯（度）を求める。
    PNG でも FITS と同じく y は下から数える（2026-11-21 にカストルとポルックスの位置で確認）。"""
    height = float(values.get("NAXIS2") or 2 * float(values["CRPIX2"]) - 1)
    x, y = col + 1.0, height - row
    dx, dy = x - float(values["CRPIX1"]), y - float(values["CRPIX2"])
    xi = math.radians(float(values["CD1_1"]) * dx + float(values["CD1_2"]) * dy)
    eta = math.radians(float(values["CD2_1"]) * dx + float(values["CD2_2"]) * dy)
    ra0, dec0 = math.radians(float(values["CRVAL1"])), math.radians(float(values["CRVAL2"]))
    denom = math.cos(dec0) - eta * math.sin(dec0)
    ra = ra0 + math.atan2(xi, denom)
    dec = math.atan2(math.sin(dec0) + eta * math.cos(dec0), math.hypot(xi, denom))
    return math.degrees(ra) % 360.0, math.degrees(dec)


def distinct_exposures(frames, change=3.0):
    """続くコマから、露出ごとに 1 枚（次の露出に変わる直前のコマ）を返す。最初の露出は途中から
    読み始めたかもしれないので使わない。差はコマを 4 画素おきに間引いた明るさの差の平均。"""
    import numpy as np
    previous = None
    in_exposure = False
    for frame in frames:
        if previous is not None:
            diff = float(np.abs(frame[::4, ::4].astype(np.int16) - previous[::4, ::4]).mean())
            if diff > change:
                if in_exposure:
                    yield previous
                in_exposure = True
        previous = frame


def grab_finder_stack(url, path, frames=8, crop_x=160, width=1920, height=1080, timeout=30, change=3.0):
    """配信から違う露出のコマを frames 枚集めて平均し、16 ビットのグレーの PNG にする。

    ファインダーは約 0.5 秒露出なのに配信は 30fps なので、同じ露出のコマが約 15 枚続き、その間の
    小さな差は動画の圧縮による（2026-11-22 実測: 露出が変わるとコマ間の差の平均が約 6、同じ露出の
    間は 1 未満）。差が change を超える直前のコマを、その露出の代表として 1 枚ずつ使う。
    ざらつき（偶然のノイズ）は √frames 分の 1 になる。左端の縞のような決まった模様は減らない。
    架台を止めて撮るので、8 枚（約 4 秒）なら星の流れは 1 画素ほどで、位置合わせはしない。"""
    import numpy as np
    w = width - 2 * crop_x
    size = w * height
    vf = f"crop={w}:{height}:{crop_x}:0" if crop_x else "null"
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
            "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    end = time.monotonic() + timeout

    def read():
        while time.monotonic() < end:
            data = proc.stdout.read(size)
            if len(data) < size:
                return
            yield np.frombuffer(data, np.uint8).reshape(height, w)

    picked = []
    try:
        for frame in distinct_exposures(read(), change):
            picked.append(frame.astype(np.float32))
            if len(picked) >= frames:
                break
    finally:
        proc.kill()
        proc.wait()
    if not picked:
        return 0
    mean = np.mean(picked, axis=0)
    out = np.clip(mean * 256.0, 0, 65535).astype("<u2")
    result = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray16le",
                             "-s", f"{w}x{height}", "-i", "-", "-pix_fmt", "gray16be", str(path)],
                            input=out.tobytes(), capture_output=True, timeout=30)
    return len(picked) if result.returncode == 0 else 0


def grab_finder(url, path, crop_x=160, timeout=20):
    """配信から 1 コマを PNG で取る。左端の縞（2026-11-21）を避けるため左右を同じ幅で切り、中心を保つ。"""
    vf = f"crop=iw-{2 * crop_x}:ih:{crop_x}:0" if crop_x else "null"
    # 最初のコマは古いことがあるので、3 コマ目まで読んで最後を残す
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", url,
            "-frames:v", "3", "-update", "1", "-vf", vf, str(path)]
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and Path(path).exists()


class PlateAlignment:
    """自動アラインメントの進行。動かす・撮る・解く・保存する部分は呼び出し側が渡す。

    hooks:
      raw() -> 軸の角度 {"az", "alt"}
      move(axis_target) -> 目標移動を終えるまで待つ。失敗は例外
      stop()            -> 架台を止める
      capture(path) -> bool
      solve(path, hint_radec, radius) -> Solver.solve の結果か None（照準の画素の向きを返す）
      altaz_of(ra_hours, dec, unix_time) -> (方位, 高度)
      radec_of(az, alt) -> (赤経 時, 赤緯 度)
      avoid(az, alt) -> 避ける理由の文字列か None（月、太陽）
      commit(params, points, errors) -> 結果を保存する
    """

    def __init__(self, hooks, start_params, mask, tolerance=0.1, points=3, max_points=5, max_attempts=8,
                 alt_band=(30.0, 50.0), workdir=None, settle=2.0, move_step=40.0, az_span=175.0):
        self.h = hooks
        self.params = dict(alignment_model.params_of(start_params or {}))
        self.mask = mask
        self.tolerance = tolerance
        self.want_points = points
        self.max_points = max_points
        self.max_attempts = max_attempts
        self.alt_band = alt_band
        self.workdir = workdir
        self.settle = settle
        self.move_step = move_step
        self.az_span = az_span
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.status = {"state": "idle", "message": "", "points": [], "rms": None, "max_error": None,
                       "params": None, "started": None, "alt_band": list(alt_band)}
        self.thread = None
        self.samples = []  # (raw, sky)
        self.rejected = []  # 解けなかった方位

    # 進行の状態（画面に出す）
    def snapshot(self):
        with self.lock:
            return {**self.status, "points": [dict(p) for p in self.status["points"]]}

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def _point(self, index, **values):
        with self.lock:
            self.status["points"][index].update(values)

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        self._set(state="running", message="開始します", started=time.time(), points=[])
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancelled.set()

    # 点の選び方
    def alt_for(self, n):
        """n 点目の高度。帯の下端・上端・中ほどを順に使い、傾きを求めやすくする。下限より 5° は上げる。"""
        lo = max(self.alt_band[0], self.mask["min_alt"] + 5.0)
        hi = max(lo, self.alt_band[1])
        return (lo, hi, (lo + hi) / 2)[n % 3]

    def choose(self, n):
        """n 点目（0 始まり）の本当の方位・高度。1 点目は今の向き、2 点目以降は既にある点から方位で最も離れた所。"""
        alt = self.alt_for(n)
        here = alignment_model.sky_of(self.params, self.h["raw"]())
        used = [p["az"] for p in self.status["points"] if p["state"] == "solved"]
        candidates = []
        for i in range(SKY_BINS):
            az = (i + 0.5) * 360.0 / SKY_BINS
            if not self.mask["bins"][i]:
                continue
            if any(abs(alignment_model.wrap180(az - r)) < 15.0 for r in self.rejected):
                continue
            axis = alignment_model.axis_of(self.params, az, alt, 0.0)
            if abs(axis["az"]) > self.az_span:
                continue
            if self.h["avoid"](az, alt):
                continue
            if used:
                spread = min(abs(alignment_model.wrap180(az - u)) for u in used)
                score = spread
            else:
                score = -abs(alignment_model.wrap180(az - here["az"]))
            candidates.append((score, az))
        if not candidates:
            return None
        if not used:
            # 1 点目は今の向き（電源を入れた方位）の近く
            return max(candidates)[1], alt
        best = max(candidates)
        if best[0] < 20.0:
            return None
        return best[1], alt

    # 動かす（各軸 move_step 以内に分ける）
    def move_to(self, az, alt):
        target = alignment_model.axis_of(self.params, az, alt, 0.0)
        while True:
            if self.cancelled.is_set():
                raise Cancelled()
            here = self.h["raw"]()
            step = {}
            done = True
            for axis in ("az", "alt"):
                delta = target[axis] - here[axis]
                if abs(delta) > self.move_step:
                    delta = math.copysign(self.move_step, delta)
                    done = False
                step[axis] = here[axis] + delta
            self.h["move"](step)
            if done:
                return

    def _run(self):
        try:
            self._align()
        except Cancelled:
            self._set(state="cancelled", message="中止しました")
            try:
                self.h["stop"]()
            except Exception:
                pass
        except Exception as e:  # 架台の見張りの停止など。結果は保存しない
            self._set(state="failed", message=f"止まりました: {e}")
            try:
                self.h["stop"]()
            except Exception:
                pass

    def _align(self):
        workdir = Path(self.workdir or tempfile.mkdtemp(prefix="plate-"))
        workdir.mkdir(parents=True, exist_ok=True)
        attempts = 0
        n_solved = 0
        while True:
            if self.cancelled.is_set():
                raise Cancelled()
            errors = self.status.get("errors") or []
            enough = n_solved >= self.want_points
            good = enough and errors and max(errors) <= self.tolerance
            if good or n_solved >= self.max_points:
                break
            if attempts >= self.max_attempts:
                break
            target = self.choose(n_solved)
            if target is None:
                break
            attempts += 1
            az, alt = target
            index = len(self.status["points"])
            with self.lock:
                self.status["points"].append({"az": az, "alt": alt, "state": "moving", "error": None})
            self._set(message=f"{index + 1} 点目へ移動中（方位 {az:.0f}°、高度 {alt:.0f}°）")
            self.move_to(az, alt)
            time.sleep(self.settle)
            self._point(index, state="solving")
            self._set(message=f"{index + 1} 点目を解いています")
            solved = self._solve_here(workdir / f"point{index + 1}.png", first=n_solved == 0)
            if solved is None:
                self._point(index, state="failed")
                self.rejected.append(az)
                self._set(message=f"{index + 1} 点目は解けなかったので、別の方位に替えます")
                continue
            raw, sky, info = solved
            self.samples.append((raw, sky))
            n_solved += 1
            self.params, errs = alignment_model.fit(self.samples, start=self.params)
            solved_points = [p for p in self.status["points"] if p["state"] == "solved"]
            self._point(index, state="solved", raw=raw, sky=sky, seconds=round(info["seconds"], 1),
                        scale=round(info["scale"], 2))
            with self.lock:
                for p, e in zip(solved_points + [self.status["points"][index]], errs):
                    p["error"] = e
                self.status["errors"] = errs
            self._set(params=dict(self.params), rms=math.sqrt(sum(e * e for e in errs) / len(errs)),
                      max_error=max(errs))
        errs = self.status.get("errors") or []
        if n_solved == 0:
            self._set(state="failed", message="1 点も解けませんでした。空の範囲とファインダーの露出を確かめてください")
            return
        ok = n_solved >= 2 and max(errs) <= self.tolerance
        self.h["commit"](dict(self.params), [p for p in self.status["points"] if p["state"] == "solved"], errs)
        if ok:
            self._set(state="done", message=f"アラインメント終了（{n_solved} 点、最大の誤差 {max(errs) * 60:.1f}′）")
        else:
            reason = "点が足りません" if n_solved < 2 else f"誤差が許容範囲（{self.tolerance * 60:.0f}′）を超えています"
            self._set(state="done_warn",
                      message=f"保存しましたが、{reason}（{n_solved} 点、最大の誤差 {max(errs) * 60:.1f}′）")

    def _solve_here(self, path, first):
        """今の向きで撮って解く。ヒントで解けなければ、ヒントなしでもう一度。"""
        raw = dict(self.h["raw"]())
        before = time.time()
        if not self.h["capture"](path):
            return None
        # 何枚か重ねるときは、撮っていた間の中ほどの時刻にする
        stamp = (before + time.time()) / 2
        guess = alignment_model.sky_of(self.params, raw)
        hint = self.h["radec_of"](guess["az"], guess["alt"])
        info = self.h["solve"](path, hint, 25.0 if first else 10.0)
        if info is None:
            if self.cancelled.is_set():
                raise Cancelled()
            info = self.h["solve"](path, None, None)
        if info is None:
            return None
        az, alt = self.h["altaz_of"](info["ra_hours"], info["dec"], stamp)
        return raw, {"az": az, "alt": alt}, info


class Cancelled(Exception):
    pass


def cleanup(path):
    try:
        os.remove(path)
    except OSError:
        pass


class Centering:
    """導入のあと、ファインダーで解いて目標へ寄せる（計画書の手順「導入のたび」）。

    架台の止まる位置は点ごとに 0.2〜0.3° ばらつくので（2026-11-22 実測）、向きのモデルだけでは主鏡の
    視野（縦 0.27°）に入らないことがある。今の向きを解き、目標との差を軸の角度に直して動かすのを、
    差が tolerance 以下になるか rounds 回まで繰り返す。

    hooks:
      wait_goto() -> 先に始めた導入が終わるまで待つ。失敗は例外
      track() -> 目標の追尾を始める（開始時の差を保つ）。解く間も星を止めておくため、動かすたびに呼ぶ
      move(axis_target) -> 追尾を止めて目標移動し、終わるまで待つ
      raw(), stop(), capture(path), solve(path, hint, radius), altaz_of(ra, dec, t),
      radec_of(az, alt) -> PlateAlignment と同じ
      params() -> 今の向きのモデル
      target_altaz(unix_time) -> 目標の本当の方位・高度
      done(result) -> 終わったら呼ぶ（成功でも失敗でも。中止のときは呼ばない）
    """

    def __init__(self, hooks, label, tolerance=0.03, rounds=3, workdir=None, settle=1.0, max_step=2.0):
        self.h = hooks
        self.label = label
        self.tolerance = tolerance
        self.rounds = rounds
        self.workdir = workdir
        self.settle = settle
        self.max_step = max_step  # 1 回に寄せる量の上限（度）。解き違いで大きく動かないように
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.status = {"state": "idle", "label": label, "message": "", "rounds": [], "error": None, "ended": None}
        self.thread = None

    def snapshot(self):
        with self.lock:
            return {**self.status, "rounds": [dict(r) for r in self.status["rounds"]]}

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        self._set(state="running", message=f"{self.label}へ導入中")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancelled.set()

    def _run(self):
        try:
            result = self._center()
        except Cancelled:
            self._set(state="cancelled", message="中止しました", ended=time.time())
            return
        except Exception as e:
            self._set(state="failed", message=f"止まりました: {e}", ended=time.time())
            try:
                self.h["stop"]()
            except Exception:
                pass
            return
        self._set(ended=time.time())
        self.h["done"](result)

    def _center(self):
        self.h["wait_goto"]()
        self.h["track"]()
        workdir = Path(self.workdir or tempfile.mkdtemp(prefix="center-"))
        workdir.mkdir(parents=True, exist_ok=True)
        error = None
        for n in range(1, self.rounds + 1):
            if self.cancelled.is_set():
                raise Cancelled()
            time.sleep(self.settle)
            self._set(message=f"ファインダーで解いています（{n} 回目）")
            raw = dict(self.h["raw"]())
            params = self.h["params"]()
            before = time.time()
            path = workdir / f"center{n}.png"
            if not self.h["capture"](path):
                self._set(state="unsolved", message="ファインダーの映像を取れませんでした")
                return {"ok": False, "error": error}
            stamp = (before + time.time()) / 2
            guess = alignment_model.sky_of(params, raw)
            info = self.h["solve"](path, self.h["radec_of"](guess["az"], guess["alt"]), 5.0)
            if info is None and not self.cancelled.is_set():
                info = self.h["solve"](path, self.h["radec_of"](guess["az"], guess["alt"]), 15.0)
            if self.cancelled.is_set():
                raise Cancelled()
            if info is None:
                state = "unsolved"
                message = "ファインダーで解けなかったので、モデルの向きのままです" if n == 1 else \
                    f"{n} 回目は解けませんでした（直前の差 {error * 60:.1f}′）"
                self._set(state=state, message=message)
                return {"ok": False, "error": error}
            s_az, s_alt = self.h["altaz_of"](info["ra_hours"], info["dec"], stamp)
            t_az, t_alt = self.h["target_altaz"](stamp)
            error = alignment_model.separation(s_az, s_alt, t_az, t_alt)
            with self.lock:
                self.status["rounds"].append({"error": error, "seconds": round(info["seconds"], 1)})
                self.status["error"] = error
            if error <= self.tolerance:
                self._set(state="done", message=f"{self.label}を中央に入れました（差 {error * 60:.1f}′、{n} 回解いた）")
                return {"ok": True, "error": error}
            if n == self.rounds:
                break
            if error > self.max_step:
                self._set(state="unsolved", message=f"差が {error:.1f}° と大きすぎるので寄せません。アラインメントを確かめてください")
                return {"ok": False, "error": error}
            # 解いた向きと目標の差を、モデルで軸の角度の差に直す。追尾中なので、撮った時刻の軸の角度は
            # 今の読み取りから追尾で進んだ分を戻して求める代わりに、差だけを今の読み取りに足す
            got = alignment_model.axis_of(params, s_az, s_alt, raw["az"])
            want = alignment_model.axis_of(params, t_az, t_alt, raw["az"])
            # 寄せている間も星は動くので、動き終わるころ（約 lead 秒後）の目標の動きを足す
            lead = 4.0
            now = dict(self.h["raw"]())
            later = time.time() + lead
            l_az, l_alt = self.h["target_altaz"](later)
            n_az, n_alt = self.h["target_altaz"](time.time())
            move_ahead = {a: v for a, v in zip(("az", "alt"),
                          (alignment_model.wrap180(l_az - n_az), l_alt - n_alt))}
            target = {a: now[a] + (want[a] - got[a]) + move_ahead[a] for a in ("az", "alt")}
            self._set(message=f"差 {error * 60:.1f}′ を寄せています（{n} 回目）")
            self.h["move"](target)
            self.h["track"]()
        self._set(state="done_warn", message=f"{self.rounds} 回寄せても差が {error * 60:.1f}′ 残りました")
        return {"ok": False, "error": error}
