"""Web API と SPA の配信。状態の正本はホストに置き、WebSocket で全端末へ流す。"""
import asyncio
import glob
import json
import math
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

import serial
from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import alignment as alignment_model
from .camera import Camera
from .capture import Capture, CaptureError
from .config import ROOT, resolve
from .guiding import FrameReader, Guider, apply_correction, field_rotation_rate
from .direct_mount import DirectMount
from .mount import Mount, MountError
from .safety import Reference, SafetyError, check_sun
from .sky import LABELS, Sky, TargetError, format_radec
from .sky import resolve as resolve_target
from .state import StateStore

STATUS_INTERVAL = 0.5
MOUNT_RETRY_INTERVAL = 3.0
SEND_TIMEOUT = 2.0
COMM_ERRORS = (MountError, serial.SerialException, OSError)
ALIGNMENT_STARS = {"polaris": "北極星"}
# SynScan 本体のアライメントが済んでいるときの校正（`z` をそのまま方位・高度として使う）
SYNSCAN_ALIGNMENT = {"star": "synscan", "source": "synscan", "az_offset": 0.0, "alt_offset": 0.0}
TARGETS = {"polaris": "北極星", "capella": "カペラ", "vega": "ベガ", "altair": "アルタイル",
           "moon": "月", "jupiter": "木星", "saturn": "土星"}
# 画面の追尾の一覧に出す天体。ほかの天体も名前か赤経・赤緯で指定できる
TRACK_TARGETS = {"moon": "月", "jupiter": "木星", "saturn": "土星", "uranus": "天王星", "capella": "カペラ",
                 "vega": "ベガ", "alcyone": "プレアデス", "m1": "M1", "m42": "M42", "m31": "M31"}
# 自動導入の計画の条件
GOTO_MIN_ALT = 10.0  # 目標の高度の下限（度）
GOTO_MAX_ALT = 80.0  # 上限。高度 90° 付近は読み取りが裏返る
GOTO_MAX_DEG = 45.0  # 1 回の導入で各軸を動かしてよい量（度）
GOTO_ALT_MARGIN = 5.0  # 途中の高度が、出発と目標の間からはみ出してよい量（度）
GOTO_PLAN_TTL = 120.0  # 計画を確認してから実行できるまでの時間（秒）
GOTO_REPLAN_TOLERANCE = 3.0  # 確認した計画と実行時の計画の差の上限（度）
DIRECT_GOTO_MAX_ALT = 88.0  # 直結版は天頂付近でも読み取りが裏返らない（2026-11-14 に 93° まで確認）


class MountSupervisor:
    """架台への接続を保つ。電源断やケーブルの抜けから戻ったら接続し直す。

    enabled を False にすると、架台を止めてシリアルを手放し、接続し直さない。SynScan の
    手元操作（アライメントなど）の間に使う。映像の配信はそのまま続く。"""

    def __init__(self, cfg, on_tick=lambda mount: None, on_connect=lambda mount: None, enabled=True,
                 on_release=lambda mount: None, flip_hint=lambda: None, reference=lambda: None):
        self.cfg = cfg
        self.backend = cfg.get("backend", "synscan")
        self.reference = reference  # 直結版の接続時に渡す向きの基準
        self.on_tick = on_tick
        self.on_connect = on_connect
        self.on_release = on_release  # シリアルを手放す直前に呼ぶ（裏返りの状態の保存など）
        self.flip_hint = flip_hint
        self.mount = None
        self.enabled = enabled
        self.lock = threading.Lock()
        self.closing = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def set_enabled(self, enabled):
        """接続を切るときは、架台を止めてからシリアルを閉じる。止められなくても閉じる。"""
        with self.lock:
            self.enabled = enabled
            mount = None
            if not enabled:
                mount, self.mount = self.mount, None
        if mount:
            try:
                mount.stop("接続を切るため停止")
            except COMM_ERRORS:
                pass
            self.on_release(mount)
            try:
                mount.close()
            except COMM_ERRORS:
                pass
            print("mount disconnected by request", flush=True)
        self.wake.set()

    def _port(self):
        if self.backend == "direct":
            direct = self.cfg.get("direct", {})
            if direct.get("port", "auto") != "auto":
                return direct["port"]
            ports = glob.glob(direct.get("port_glob", "/dev/serial/by-id/*SynHub*"))
            return ports[0] if ports else None
        if self.cfg["port"] != "auto":
            return self.cfg["port"]
        ports = glob.glob("/dev/serial/by-id/*Serial*")
        return ports[0] if ports else None

    def _connect(self, port):
        if self.backend == "direct":
            return DirectMount(port, self.cfg.get("direct", {}), reference=self.reference())
        backlash = self.cfg.get("backlash")
        return Mount(port, self.cfg["max_rate"], self.cfg["az_limit"], self.cfg["alt_limit"],
                     backlash=backlash,
                     speeds=self.cfg.get("speeds") or (backlash or {}).get("speeds"),
                     max_move_deg=self.cfg.get("max_move_deg", 45.0),
                     max_move_seconds=self.cfg.get("max_move_seconds", 120.0),
                     jump_deg=self.cfg.get("jump_deg", 5.0), flip_hint=self.flip_hint())

    def _run(self):
        while not self.closing.is_set():
            mount = self.mount
            if mount and mount.error and not os.path.exists(mount.serial.port):
                self.mount = None
                try:
                    mount.close()
                except COMM_ERRORS:
                    pass
            elif mount is None and self.enabled and (port := self._port()):
                try:
                    mount = self._connect(port)
                except COMM_ERRORS as e:
                    print(f"mount not available: {e}", flush=True)
                else:
                    with self.lock:
                        # 接続している間に切断を頼まれていたら、使わずに閉じる
                        keep = self.enabled
                        if keep:
                            self.mount = mount
                    if keep:
                        print(f"mount connected: {port}", flush=True)
                        try:
                            self.on_connect(mount)
                        except COMM_ERRORS as e:
                            print(f"mount check after connect failed: {e}", flush=True)
                    else:
                        mount.close()
            elif mount:
                try:
                    self.on_tick(mount)
                except COMM_ERRORS:
                    pass
            self.wake.wait(MOUNT_RETRY_INTERVAL)
            self.wake.clear()

    def close(self):
        self.closing.set()
        self.wake.set()
        mount, self.mount = self.mount, None
        if mount:
            self.on_release(mount)
            try:
                mount.close()
            except COMM_ERRORS:
                pass


def parse_site(body):
    """画面から送られた観測地を確かめる。緯度と経度は度、標高は m。"""
    try:
        lat, lon = float(body["latitude"]), float(body["longitude"])
        elevation = float(body.get("elevation_m", 0.0))
    except (KeyError, TypeError, ValueError):
        raise ValueError("緯度、経度、標高を数値で指定してください")
    if not all(map(math.isfinite, (lat, lon, elevation))):
        raise ValueError("緯度、経度、標高を数値で指定してください")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("緯度または経度が範囲外です")
    if not -500 <= elevation <= 9000:
        raise ValueError("標高が範囲外です")
    source = body.get("source")
    site = {"latitude": lat, "longitude": lon, "elevation_m": elevation,
            "source": source if source in ("phone", "map") else "manual"}
    # 誤差と標高の内訳は表示用。計算に使うのは elevation_m（楕円体高）だけ
    for key in ("accuracy_m", "ground_m", "height_m", "geoid_m"):
        value = body.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            site[key] = float(value)
    return site


GSI_ELEVATION = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?lon={lon}&lat={lat}&outtype=JSON"
GSI_GEOID = ("https://vldb.gsi.go.jp/sokuchi/surveycalc/geoid/calcgh/cgi/geoidcalc.pl"
             "?outputType=json&latitude={lat}&longitude={lon}")


def parse_elevation(text):
    """地理院の標高 API の応答から、地面の標高（m）と元のデータの種類を取り出す。海域などは None。"""
    try:
        body = json.loads(text)
        return float(body["elevation"]), str(body.get("hsrc", ""))
    except (ValueError, TypeError, KeyError):
        return None, None


def parse_geoid(text):
    """地理院のジオイド高計算の応答から、ジオイド高（m）を取り出す。"""
    try:
        value = float(json.loads(text)["OutputData"]["geoidHeight"])
    except (ValueError, TypeError, KeyError):
        return None
    return value if math.isfinite(value) else None


def fetch_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": "observatory"})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def lookup_site(lat, lon):
    """地点の地面の標高とジオイド高を地理院から取得する。インターネットがなければ None を返す。"""
    elevation_text = fetch_text(GSI_ELEVATION.format(lat=lat, lon=lon))
    geoid_text = fetch_text(GSI_GEOID.format(lat=lat, lon=lon))
    ground, source = parse_elevation(elevation_text) if elevation_text else (None, None)
    if ground is not None and not math.isfinite(ground):
        ground = None
    return {"ground_m": ground, "ground_source": source,
            "geoid_m": parse_geoid(geoid_text) if geoid_text else None}


def post_sdp(url, offer):
    request = urllib.request.Request(url, offer, {"Content-Type": "application/sdp"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError:
        return 502, b""


def goto_plan(here, target, offset, limits, label):
    """自動導入の計画を作る。here と target は {"az", "alt"}（本当の方位・高度）、offset と limits は
    架台の範囲制限の相対角度。各軸の向きと量、途中の高度の範囲、時間の上限を返す。導入できなければ TargetError。"""
    d_az = alignment_model.wrap180(target["az"] - here["az"])
    d_alt = target["alt"] - here["alt"]
    if target["alt"] < GOTO_MIN_ALT:
        raise TargetError(f"目標の高度が {target['alt']:.1f}° で、{GOTO_MIN_ALT:.0f}° より低いので導入しません")
    if target["alt"] > GOTO_MAX_ALT:
        raise TargetError(f"目標の高度が {target['alt']:.1f}° で、{GOTO_MAX_ALT:.0f}° より高いので導入しません（天頂付近は読み取りが裏返ります）")
    if abs(d_az) > GOTO_MAX_DEG or abs(d_alt) > GOTO_MAX_DEG:
        raise TargetError(f"移動が大きすぎます（方位 {d_az:+.1f}°、高度 {d_alt:+.1f}°）。"
                          f"各軸 {GOTO_MAX_DEG:.0f}° 以内になるよう、途中の天体を経由してください")
    for axis, delta in (("az", d_az), ("alt", d_alt)):
        if abs(offset[axis] + delta) >= limits[axis]:
            raise TargetError(f"{axis} が範囲の上限（接続時の位置から ±{limits[axis]:.0f}°）を越えるので導入しません")
    return {"label": label,
            "from": {"az": here["az"], "alt": here["alt"]}, "to": {"az": target["az"], "alt": target["alt"]},
            "az_direction": 1 if d_az >= 0 else -1, "az_amount": abs(d_az), "d_az": d_az, "d_alt": d_alt,
            "alt_range": [min(here["alt"], target["alt"]) - GOTO_ALT_MARGIN,
                          min(max(here["alt"], target["alt"]) + GOTO_ALT_MARGIN, GOTO_MAX_ALT + GOTO_ALT_MARGIN)],
            "timeout": min(20.0 + 1.5 * max(abs(d_az), abs(d_alt)), 120.0)}


def describe_plan(plan):
    az = f"方位 {'東回り（右）' if plan['d_az'] >= 0 else '西回り（左）'}に {abs(plan['d_az']):.1f}°"
    alt = f"高度 {'上' if plan['d_alt'] >= 0 else '下'}へ {abs(plan['d_alt']):.1f}°"
    low, high = plan["alt_range"]
    return (f"{az}、{alt}。止める条件: 方位が逆に 5° 以上か計画より 8° 以上多く回る、"
            f"高度が {low:.0f}〜{high:.0f}° の外、{plan['timeout']:.0f} 秒を超える、読み取りが飛ぶ")


def describe_direct_plan(plan):
    az = f"方位 {'東回り（右）' if plan['d_az'] >= 0 else '西回り（左）'}に {abs(plan['d_az']):.1f}°"
    alt = f"高度 {'上' if plan['d_alt'] >= 0 else '下'}へ {abs(plan['d_alt']):.1f}°"
    return (f"{az}、{alt}。基板の目標移動で動き、最後は + 向きから近づけます。止める条件: 範囲の外、"
            f"時間切れ、読み取りの飛び・停滞・頼んでいない動き")


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def create_app(cfg):
    camera = Camera(cfg["camera"]["device"], cfg["server"]["mediamtx_api"])
    finder_cfg = cfg["finder"]
    finder_camera = Camera(finder_cfg["device"], cfg["server"]["mediamtx_api"], "finder",
                           finder_cfg["exposure_range"], finder_cfg["gain_range"])
    store = StateStore(resolve(cfg["server"]["state_file"]))
    # 画面から保存した観測地があれば、設定ファイルより優先する
    site = {"elevation_m": 0.0, "source": "config", **cfg["site"], **(store.get()["site"] or {})}
    sky = Sky(site["latitude"], site["longitude"], site["elevation_m"])
    notice = {"message": ""}
    direct = cfg["mount"].get("backend", "synscan") == "direct"
    direct_cfg = cfg["mount"].get("direct", {})

    def reference_of(state):
        """直結版の向きの基準。登録したアラインメント（北・水平、目標、星）のずれをそのまま使う。"""
        current = state["alignment"]
        if not current:
            return None
        return Reference(kind=current.get("source", "star"), az_offset=current["az_offset"],
                         alt_offset=current["alt_offset"], label=current.get("label", current.get("star", "")))

    def apply_reference():
        mount = supervisor.mount
        if direct and mount:
            mount.set_reference(reference_of(store.get()))

    def landmarks_here():
        return [m for m in direct_cfg.get("landmarks", [])
                if distance_km(site["latitude"], site["longitude"], m["latitude"], m["longitude"]) <= m.get("radius_km", 1.0)]

    def check_alignment(mount):
        # 架台の電源が入り直されると読み取りが 0 に戻るので、古い校正を使わない。
        # SynScan の手元操作で時計を設定し直したときも、時計がずれるのでここで外れる
        current = store.get()["alignment"]
        if current and not alignment_model.still_valid(current, mount.clock()):
            store.update(alignment=None)
            notice["message"] = "架台の電源か時計が変わったため、アラインメントを解除しました"
            print(notice["message"], flush=True)

    # target は resolve() の結果。サーバーが計算した速度で追尾する
    tracking = {"target": None}
    synscan = {"mode": None, "label": None}  # SynScan 本体の追尾（`t`）と、その対象の名前
    goto_plans = {}

    def clear_tracking():
        tracking["target"] = None
        guider.stop()

    def update_tracking(mount):
        if tracking["target"] is None:
            return
        # 緊急停止や範囲の上限で止まったら、追尾の状態も解除する
        if not mount.status()["tracking"]:
            clear_tracking()
            return
        az, alt = sky.rates(tracking["target"])
        correction = guider.correction()
        mount.update_track({"az": apply_correction(az, correction["az"]),
                            "alt": apply_correction(alt, correction["alt"])})

    def save_flip(mount):
        # 再起動や接続し直しのあとも、高度の読み取りの裏返りの状態を引き継げるようにする
        status_now = mount.status()
        if status_now["reported"] is None:
            return
        current = {"flipped": status_now["flipped"], "reported": status_now["reported"]}
        saved = store.get().get("mount_flip")
        if saved != current:
            store.update(mount_flip=current)

    def on_mount_tick(mount):
        if direct:
            # 見張りが未初期化への戻り（瞬断など）を見つけると、架台は制限モードに戻る。登録も外す
            if mount.status()["restricted"] and store.get()["alignment"]:
                store.update(alignment=None)
                notice["message"] = "架台の初期化が外れたため、向きの基準を解除しました。選び直してください"
                print(notice["message"], flush=True)
            update_tracking(mount)
            return
        check_alignment(mount)
        # 架台の電源の入れ直しなどで、SynScan のアライメントが外れることがある
        check_synscan(mount)
        update_tracking(mount)
        if not mount.status()["goto"]:
            synscan["mode"] = mount.tracking_mode()
            if synscan["mode"] == "off":
                synscan["label"] = None
        if mount.status()["flipped"] != (store.get().get("mount_flip") or {}).get("flipped", False):
            save_flip(mount)

    def check_synscan(mount):
        # SynScan 本体のアライメントの有無で `z` の値の意味が変わるので、変わったら古い校正を使わない
        aligned = mount.synscan_aligned()
        state = store.get()
        previous = state.get("synscan_aligned")
        if previous is not None and previous != aligned and state["alignment"]:
            store.update(alignment=None)
            notice["message"] = "SynScan のアライメントの状態が変わったため、アラインメントを解除しました"
            print(notice["message"], flush=True)
        if previous != aligned:
            store.update(synscan_aligned=aligned)
            print(f"synscan aligned: {aligned}", flush=True)

    def on_mount_connect(mount):
        if direct:
            if mount.fresh_power_on and store.get()["alignment"]:
                store.update(alignment=None)
                notice["message"] = "架台の電源が入り直されたので、向きの基準を選び直してください"
                print(notice["message"], flush=True)
            mount.set_reference(reference_of(store.get()))
            return
        check_synscan(mount)
        synscan["mode"] = mount.tracking_mode()

    def effective_alignment(state):
        """画面で登録したアラインメント。なければ、SynScan 本体のアライメントが済んでいるとき、
        `z` が本当の方位・高度なので、差 0 の校正として扱う。"""
        if state["alignment"]:
            return state["alignment"]
        if state.get("synscan_aligned"):
            return SYNSCAN_ALIGNMENT
        return None

    supervisor = MountSupervisor(cfg["mount"], on_mount_tick, on_mount_connect,
                                 enabled=store.get().get("mount_enabled", True),
                                 on_release=save_flip, flip_hint=lambda: store.get().get("mount_flip"),
                                 reference=lambda: reference_of(store.get()))

    def guide_context():
        recording = store.get()["recording"]
        mount = supervisor.mount
        moving = not mount or bool(mount.status()["moving"])
        target = tracking["target"]
        az, alt = sky.altaz(target) if target else (0.0, 0.0)
        return {"paused": moving or recording.get("kind") == "still" or recording.get("state") in ("starting", "stopping"),
                "mode": "timelapse" if recording.get("kind") == "timelapse" else "live",
                "cos_alt": math.cos(math.radians(alt)),
                "rotation": field_rotation_rate(site["latitude"], az, alt)}

    guider = Guider(FrameReader("rtsp://127.0.0.1:8554/camera"), guide_context)

    def mount_raw():
        mount = supervisor.mount
        return mount.status()["raw"] if mount else None

    capture = Capture(cfg["capture"], cfg["camera"]["device"], store, camera, mount_raw,
                      resolve(cfg["capture"]["root"]), resolve(cfg["capture"]["preview_dir"]))
    clients = set()

    def snapshot():
        mount = supervisor.mount
        mount_status = mount.status() if mount else None
        controls = camera.controls()
        online = camera.stream_online()
        mount_ok = bool(mount_status) and not mount_status["error"]
        state = store.get()
        return {
            "type": "status",
            "time": time.time(),
            "system": {"ok": online and controls is not None and mount_ok,
                       "camera": online and controls is not None, "mount": mount_ok},
            # connected / connecting（接続を試みている）/ disconnected（手動で切断中）
            "mount_connection": "connected" if mount else "connecting" if supervisor.enabled else "disconnected",
            "alignment": effective_alignment(state),
            "finder": state["finder"],
            # 方位と高度はアラインメントが済むまで値を持たない
            "pointing": alignment_model.pointing(effective_alignment(state), mount_status["raw"])
                        if effective_alignment(state) and mount_ok else None,
            "notice": notice["message"],
            "tracking": {"target": tracking["target"]["key"] if tracking["target"] else None,
                         "label": tracking["target"]["label"] if tracking["target"] else None,
                         "guide": guider.snapshot(),
                         # 速度指定の `P` で追尾している間も、SynScan の `t` は alt-az 追尾と答える（2026-11-07 実機）
                         "synscan": synscan["mode"] if mount_status and not tracking["target"] else None,
                         "synscan_label": synscan["label"]},
            "recording": capture.status(),
            "power": "ok",
            "camera": controls,
            "finder_camera": finder_camera.controls(),
            "mount": mount_status,
            "webrtc_port": cfg["server"]["webrtc_port"],
        }

    async def broadcast_loop():
        while True:
            await asyncio.sleep(STATUS_INTERVAL)
            if not clients:
                continue
            message = await asyncio.to_thread(snapshot)
            for ws in list(clients):
                try:
                    await asyncio.wait_for(ws.send_json(message), SEND_TIMEOUT)
                except Exception:
                    clients.discard(ws)

    async def lifespan(app):
        supervisor.start()
        await asyncio.to_thread(capture.start)
        task = asyncio.create_task(broadcast_loop())
        yield
        task.cancel()
        await asyncio.to_thread(capture.close)
        await asyncio.to_thread(guider.stop)
        # サーバーの終了時は架台を止めてから終わる
        await asyncio.to_thread(supervisor.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/status")
    def status():
        return snapshot()

    def stop_mount():
        """全軸を止める。SynScan 本体の追尾も切る（`P` の停止では切れない）。"""
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        error = None
        try:
            mount.stop()
        except COMM_ERRORS as e:
            error = str(e)
        try:
            mount.set_tracking_mode("off")
            synscan.update(mode="off", label=None)
        except COMM_ERRORS as e:
            error = error or str(e)
        if error:
            return JSONResponse({"error": error}, 503)
        return {"ok": True}

    @app.post("/api/mount/connection")
    def set_mount_connection(request: Request, body: dict = Body(...)):
        connected = body.get("connected")
        if not isinstance(connected, bool):
            return JSONResponse({"error": "connected を true か false で指定してください"}, 400)
        print(f"mount connection {connected} from {request.client.host if request.client else '?'}", flush=True)
        if not connected:
            clear_tracking()
        store.update(mount_enabled=connected)
        supervisor.set_enabled(connected)
        return {"ok": True, "connected": connected}

    # 緊急停止は WebSocket が切れていても効くように、単純な POST で受ける
    app.post("/api/mount/stop")(stop_mount)

    @app.get("/stop")
    def stop_page():
        return FileResponse(ROOT / "web" / "stop.html")

    @app.post("/stop")
    def stop_from_page():
        stop_mount()
        return RedirectResponse("/stop", 303)

    @app.post("/api/camera")
    def set_camera(request: Request, body: dict = Body(...)):
        print(f"camera set {body} from {request.client.host if request.client else '?'}", flush=True)
        if capture.locks_exposure():
            return JSONResponse({"error": "撮影中は露出とゲインを変更できません"}, 409)
        try:
            camera.apply(manual=body.get("manual"), exposure=body.get("exposure"), gain=body.get("gain"))
        except (ValueError, TypeError, OSError, subprocess.SubprocessError) as e:
            return JSONResponse({"error": str(e)}, 400)
        return {"ok": True}

    # ファインダーは撮影に使わないので、撮影中でも変更できる
    @app.post("/api/finder/camera")
    def set_finder_camera(request: Request, body: dict = Body(...)):
        print(f"finder camera set {body} from {request.client.host if request.client else '?'}", flush=True)
        try:
            finder_camera.apply(manual=body.get("manual"), exposure=body.get("exposure"), gain=body.get("gain"))
        except (ValueError, TypeError, OSError, subprocess.SubprocessError) as e:
            return JSONResponse({"error": str(e)}, 400)
        return {"ok": True}

    def capture_call(start, *args):
        try:
            return {"ok": True, "path": start(*args)}
        except CaptureError as e:
            return JSONResponse({"error": str(e)}, e.status)

    @app.post("/api/capture/still")
    def capture_still(body: dict = Body(default={})):
        return capture_call(capture.still, body.get("target"))

    @app.post("/api/capture/timelapse")
    def capture_timelapse(body: dict = Body(...)):
        return capture_call(capture.timelapse, body.get("interval"), body.get("target"))

    @app.post("/api/capture/video")
    def capture_video(body: dict = Body(default={})):
        return capture_call(capture.video, body.get("seconds"), body.get("target"))

    @app.post("/api/capture/stop")
    def capture_stop():
        return capture_call(capture.stop)

    @app.get("/api/captures")
    def captures():
        return {"sessions": capture.list_sessions()}

    @app.get("/api/capture/preview")
    def capture_preview():
        path = capture.preview_dir / "latest.jpg"
        if not path.exists():
            return JSONResponse({"error": "まだ画像がありません"}, 404)
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/api/alignment")
    def get_alignment():
        current = effective_alignment(store.get())
        mount = supervisor.mount
        here = alignment_model.pointing(current, mount.status()["raw"]) if current and mount else None
        time_now = sky.now()
        targets = []
        for name, label in TARGETS.items():
            az, alt = sky.altaz(name, time_now)
            target = {"name": name, "label": label, "az": az, "alt": alt}
            if here:
                target["daz"] = alignment_model.wrap180(az - here["az"])
                target["dalt"] = alt - here["alt"]
            targets.append(target)
        return {"site": site, "alignment": current, "targets": targets}

    @app.post("/api/alignment/register")
    def register_alignment(body: dict = Body(...)):
        star = body.get("star")
        if star not in ALIGNMENT_STARS:
            return JSONResponse({"error": "登録できない星です"}, 400)
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        status_now = mount.status()
        if status_now["moving"]:
            return JSONResponse({"error": "止まってから登録してください"}, 409)
        try:
            clock = mount.clock()
        except COMM_ERRORS as e:
            return JSONResponse({"error": str(e)}, 503)
        result = alignment_model.register(star, sky.altaz(star), status_now["raw"], clock)
        if direct:
            result.update(source="star", label=ALIGNMENT_STARS[star])
        store.update(alignment=result)
        apply_reference()
        notice["message"] = ""
        print(f"aligned on {star}: az_offset={result['az_offset']:.4f} alt_offset={result['alt_offset']:.4f}", flush=True)
        return result

    @app.delete("/api/alignment")
    def clear_alignment():
        store.update(alignment=None)
        apply_reference()
        return {"ok": True}

    @app.get("/api/reference")
    def get_reference():
        """直結版の向きの基準の選択肢。北・水平で電源を入れた（既定）と、この観測地に登録した目標。"""
        mount = supervisor.mount
        return {"backend": "direct" if direct else "synscan",
                "current": mount.status().get("reference") if mount and direct else None,
                "restricted": mount.status().get("restricted") if mount and direct else None,
                "options": [{"kind": "power_on", "label": "北・水平で電源を入れた"}]
                           + [{"kind": "landmark", "key": m["key"], "label": m["label"], "az": m["az"], "alt": m["alt"]}
                              for m in landmarks_here()]}

    @app.post("/api/reference")
    def set_reference(request: Request, body: dict = Body(...)):
        """向きの基準を決める。landmark は、その目標を映像の中心に入れてから呼ぶ。"""
        if not direct:
            return JSONResponse({"error": "向きの基準は直結版だけの機能です"}, 400)
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        status_now = mount.status()
        if status_now["moving"] or status_now["goto"]:
            return JSONResponse({"error": "止まってから選んでください"}, 409)
        kind = body.get("kind")
        now = time.time()
        if kind == "power_on":
            result = {"star": "power_on", "source": "power_on", "label": "北・水平で電源投入", "time": now,
                      "az_offset": 0.0, "alt_offset": 0.0, "clock_offset": mount.clock() - now}
        elif kind == "landmark":
            mark = next((m for m in landmarks_here() if m["key"] == body.get("key")), None)
            if mark is None:
                return JSONResponse({"error": "この観測地で使える目標ではありません"}, 400)
            result = alignment_model.register(mark["key"], (mark["az"], mark["alt"]), status_now["raw"], mount.clock(), now)
            result.update(source="landmark", label=mark["label"])
        else:
            return JSONResponse({"error": "kind は power_on か landmark です"}, 400)
        store.update(alignment=result)
        apply_reference()
        notice["message"] = ""
        print(f"reference {kind} from {request.client.host if request.client else '?'}: {result}", flush=True)
        return result

    @app.get("/api/site")
    def get_site():
        return site

    @app.get("/api/site/lookup")
    async def site_lookup(lat: float, lon: float):
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return JSONResponse({"error": "緯度または経度が範囲外です"}, 400)
        return await asyncio.to_thread(lookup_site, lat, lon)

    @app.post("/api/site")
    def set_site(body: dict = Body(...)):
        try:
            new = parse_site(body)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, 400)
        new["time"] = time.time()
        sky.set_site(new["latitude"], new["longitude"], new["elevation_m"])
        site.clear()
        site.update(new)
        store.update(site=new)
        print(f"site set: {new}", flush=True)
        return site

    @app.post("/api/whep/{name}")
    async def whep(name: str, request: Request):
        # 証明書の確認を 1 回で済ませるため、MediaMTX への WHEP は同じオリジンから中継する
        if name not in ("camera", "finder"):
            return JSONResponse({"error": "不明な映像です"}, 404)
        offer = await request.body()
        url = f"http://127.0.0.1:{cfg['server']['webrtc_port']}/{name}/whep"
        status_code, answer = await asyncio.to_thread(post_sdp, url, offer)
        return Response(answer, status_code, media_type="application/sdp")

    @app.post("/api/finder")
    def set_finder(body: dict = Body(...)):
        try:
            x, y = float(body["x"]), float(body["y"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "位置が読めません"}, 400)
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return JSONResponse({"error": "映像の外です"}, 400)
        store.update(finder={"x": x, "y": y})
        return {"ok": True, "x": x, "y": y}

    def lookup_target(query):
        """名前か赤経・赤緯から、今の方位・高度などを返す。"""
        target = resolve_target(query)
        now = sky.now()
        # Skyfield の値は numpy の型なので、JSON にできる float にする
        az, alt = (float(v) for v in sky.altaz(target, now))
        ra, dec = (float(v) for v in sky.radec_j2000(target, now))
        rate_az, rate_alt = (float(v) for v in sky.rates(target, now))
        result = {"key": target["key"], "label": target["label"], "kind": target["kind"],
                  "az": az, "alt": alt, "ra_hours": ra, "dec": dec, "radec": format_radec(ra, dec),
                  "rates": {"az": rate_az, "alt": rate_alt}, "above": alt > 0}
        mount = supervisor.mount
        here = mount and mount.status()["raw"]
        current = effective_alignment(store.get())
        if here and current:
            point = alignment_model.pointing(current, here)
            result["daz"] = float(alignment_model.wrap180(az - point["az"]))
            result["dalt"] = float(alt - point["alt"])
        return target, result

    @app.get("/api/sky/catalog")
    def sky_catalog():
        return {"quick": [{"key": k, "label": v} for k, v in TRACK_TARGETS.items()],
                "all": [{"key": k, "label": v} for k, v in LABELS.items()]}

    @app.get("/api/sky/lookup")
    def sky_lookup(q: str = ""):
        try:
            return lookup_target(q)[1]
        except TargetError as e:
            return JSONResponse({"error": str(e)}, 400)

    def make_plan(mount, query):
        target, info = lookup_target(query)
        if target["key"] == "sun":
            raise TargetError("太陽には向けません")
        if direct:
            return target, info, make_direct_plan(mount, target, info)
        if not store.get().get("synscan_aligned") or not mount.synscan_aligned():
            raise TargetError("SynScan 本体のアライメントが済んでいないので、自動導入は使えません")
        status_now = mount.status()
        if status_now["raw"] is None:
            raise TargetError("架台の位置が読めません")
        if status_now["jumped"]:
            raise TargetError("読み取りの飛びがあったので、自動導入は使えません。サーバーを再起動してください")
        # アライメント済みの SynScan では `z` が本当の方位・高度
        plan = goto_plan(status_now["raw"], {"az": info["az"], "alt": info["alt"]},
                         {"az": status_now["az"], "alt": status_now["alt"]}, status_now["limits"], target["label"])
        return target, info, plan

    def make_direct_plan(mount, target, info):
        """直結版の導入の計画。目標の本当の方位・高度を、基準のずれで軸の角度に直す。"""
        status_now = mount.status()
        if status_now["restricted"]:
            raise TargetError("向きの基準を選ぶまで、導入は使えません")
        if status_now["fault"]:
            raise TargetError(f"見張りが止めた状態です（{status_now['fault']}）。停止ボタンで解除してください")
        current = store.get()["alignment"]
        if info["alt"] < GOTO_MIN_ALT:
            raise TargetError(f"目標の高度が {info['alt']:.1f}° で、{GOTO_MIN_ALT:.0f}° より低いので導入しません")
        if info["alt"] > DIRECT_GOTO_MAX_ALT:
            raise TargetError(f"目標の高度が {info['alt']:.1f}° で、{DIRECT_GOTO_MAX_ALT:.0f}° より高いので導入しません")
        here = status_now["raw"]
        d_az = alignment_model.wrap180(info["az"] - current["az_offset"] - here["az"])
        d_alt = info["alt"] - current["alt_offset"] - here["alt"]
        if abs(d_az) > GOTO_MAX_DEG or abs(d_alt) > GOTO_MAX_DEG:
            raise TargetError(f"移動が大きすぎます（方位 {d_az:+.1f}°、高度 {d_alt:+.1f}°）。"
                              f"各軸 {GOTO_MAX_DEG:.0f}° 以内になるよう、途中の天体を経由してください")
        axis_target = {"az": here["az"] + d_az, "alt": here["alt"] + d_alt}
        try:
            for axis, value in axis_target.items():
                mount.envelope.check_target(axis, value)
            sun_az, sun_alt = sky.altaz("sun")
            check_sun(mount.safety, mount.reference, axis_target, (float(sun_az), float(sun_alt)))
        except SafetyError as e:
            raise TargetError(str(e))
        point = alignment_model.pointing(current, here)
        return {"label": target["label"], "from": point, "to": {"az": info["az"], "alt": info["alt"]},
                "d_az": d_az, "d_alt": d_alt, "az_direction": 1 if d_az >= 0 else -1, "az_amount": abs(d_az),
                "alt_range": [min(point["alt"], info["alt"]), max(point["alt"], info["alt"])],
                "timeout": None, "axis_target": axis_target, "backend": "direct"}

    @app.post("/api/goto/plan")
    def plan_goto(body: dict = Body(...)):
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        try:
            target, info, plan = make_plan(mount, body.get("target"))
        except TargetError as e:
            return JSONResponse({"error": str(e)}, 409)
        except COMM_ERRORS as e:
            return JSONResponse({"error": str(e)}, 503)
        now = time.monotonic()
        for key in [k for k, v in goto_plans.items() if now - v["time"] > GOTO_PLAN_TTL]:
            del goto_plans[key]
        plan_id = os.urandom(8).hex()
        goto_plans[plan_id] = {"query": body.get("target"), "plan": plan, "time": now}
        text = describe_direct_plan(plan) if direct else describe_plan(plan)
        return {"plan_id": plan_id, "plan": plan, "target": info, "text": text}

    @app.post("/api/goto")
    def run_goto(request: Request, body: dict = Body(...)):
        """確認した計画で導入する。架台か天体が計画の後に大きく動いていたら、確認し直してもらう。"""
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        saved = goto_plans.pop(str(body.get("plan_id")), None)
        if saved is None or time.monotonic() - saved["time"] > GOTO_PLAN_TTL:
            return JSONResponse({"error": "計画の確認が古いか、見つかりません。もう一度計画を確認してください"}, 409)
        try:
            target, _, plan = make_plan(mount, saved["query"])
            old = saved["plan"]
            if (abs(plan["d_az"] - old["d_az"]) > GOTO_REPLAN_TOLERANCE
                    or abs(plan["d_alt"] - old["d_alt"]) > GOTO_REPLAN_TOLERANCE):
                return JSONResponse({"error": "確認した後に架台の位置が変わりました。もう一度計画を確認してください"}, 409)
            print(f"goto requested by {request.client.host if request.client else '?'}: "
                  f"{describe_direct_plan(plan) if direct else describe_plan(plan)}", flush=True)
            clear_tracking()
            if direct:
                mount.stop("導入の前に停止")
                mount.goto_axes(plan["axis_target"], target["label"])
            else:
                ra, dec = sky.radec_j2000(target)
                mount.start_goto(ra, dec, plan)
            synscan["label"] = target["label"]
        except TargetError as e:
            return JSONResponse({"error": str(e)}, 409)
        except COMM_ERRORS as e:
            return JSONResponse({"error": str(e)}, 503)
        return {"ok": True, "plan": plan}

    @app.post("/api/tracking")
    def start_tracking(body: dict = Body(...)):
        """mode が "server"（既定）なら計算した速度で追尾し、guide で映像の補正を加える。
        "synscan" なら SynScan 本体の追尾（alt-az）に任せる。スティックで切れた追尾を戻すのに使う。"""
        mount = supervisor.mount
        if mount is None:
            return JSONResponse({"error": "架台に接続していません"}, 503)
        mode = body.get("mode", "server")
        if mode not in ("server", "synscan"):
            return JSONResponse({"error": "mode は server か synscan です"}, 400)
        try:
            if mode == "synscan":
                if not store.get().get("synscan_aligned"):
                    return JSONResponse({"error": "SynScan 本体のアライメントが済んでいないので、SynScan の追尾は使えません"}, 409)
                clear_tracking()
                mount.stop("SynScan の追尾に切り替え")
                mount.set_tracking_mode("altaz")
                label = None
                if body.get("target"):
                    label = resolve_target(body["target"])["label"]
                synscan.update(mode="altaz", label=label)
                return {"ok": True, "mode": "synscan"}
            target = resolve_target(body.get("target"))
            if target["key"] == "sun":
                return JSONResponse({"error": "太陽は追尾しません"}, 409)
            if sky.altaz(target)[1] < 0:
                return JSONResponse({"error": "地平線の下にあります"}, 409)
            az, alt = sky.rates(target)
            # SynScan 本体の追尾と重ならないよう、先に切る
            mount.set_tracking_mode("off")
            synscan.update(mode="off", label=None)
            mount.track({"az": az, "alt": alt})
        except TargetError as e:
            return JSONResponse({"error": str(e)}, 400)
        except COMM_ERRORS as e:
            return JSONResponse({"error": str(e)}, 503)
        tracking["target"] = target
        if body.get("guide"):
            guider.start()
        else:
            guider.stop()
        return {"ok": True, "mode": "server", "label": target["label"], "az": float(az), "alt": float(alt),
                "guide": bool(body.get("guide"))}

    @app.delete("/api/tracking")
    def stop_tracking():
        clear_tracking()
        return stop_mount()

    @app.websocket("/api/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        clients.add(ws)
        driving = False
        try:
            # 接続のたびに、まず現在の状態を渡す
            await ws.send_json(await asyncio.to_thread(snapshot))
            while True:
                message = await ws.receive_json()
                if message.get("type") != "stick":
                    continue
                mount = supervisor.mount
                try:
                    if mount is None:
                        raise MountError("架台に接続していません")
                    az, alt = int(message["az"]), int(message["alt"])
                    await asyncio.to_thread(mount.drive, az, alt)
                    driving = bool(az or alt)
                except (KeyError, TypeError, ValueError, *COMM_ERRORS) as e:
                    await ws.send_json({"type": "error", "message": str(e)})
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            clients.discard(ws)
            mount = supervisor.mount
            if driving and mount:
                try:
                    await asyncio.to_thread(mount.stop, "接続が切れたため停止")
                except COMM_ERRORS:
                    pass

    app.mount("/captures", StaticFiles(directory=capture.root))
    @app.middleware("http")
    async def revalidate_static(request, call_next):
        # 更新した画面が古いキャッシュのまま動かないよう、毎回ブラウザに確認させる
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True))
    return app
