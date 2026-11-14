#!/usr/bin/env python3
"""ピント合わせと手動移動の簡易サーバー（Python 標準ライブラリ、pyserial、ffmpeg、v4l2-ctl を使用）。

既定ではカメラの MJPEG を再圧縮せず、同じ LAN のブラウザへ multipart で配信する。
--webrtc を付けるとカメラは開かず、MediaMTX の WebRTC 映像を表示する。映像の FFmpeg は observatory サーバーが起動する。
架台は押している間だけ動かす。Phase 1、2 の検証用で、本番の SPA や配信経路の代わりではない。
"""
import argparse
import glob
import json
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from observatory.mount import Mount, MountError

DEVICE = "/dev/v4l/by-id/usb-SVBONY_SV205_SVBONY_SV205_200901010001-video-index0"
SIZES = ("1920x1080", "1280x720", "2592x1944", "3264x2160")
BOUNDARY = "frame"

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Focus Preview</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#000;color:#ddd;font:15px system-ui,sans-serif}
#view{height:70vh;overflow:auto;background:#000;text-align:center}
#view img,#view video{max-width:100%;max-height:100%}
#view.full img,#view.full video{max-width:none;max-height:none}
#panel{padding:12px 16px;display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center}
label{display:flex;gap:6px;align-items:center}
button,select{font:inherit;padding:6px 10px}
input[type=range]{width:180px;max-width:60vw}
#stat{width:100%;font-variant-numeric:tabular-nums}
#err{width:100%;color:#f88}
#mount{width:100%;display:none;gap:12px 20px;flex-wrap:wrap;align-items:center;border-top:1px solid #444;padding-top:12px}
#pad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,64px);gap:4px;touch-action:none;user-select:none;-webkit-user-select:none}
#pad button{font-size:15px;padding:0}
#pad button.on{background:#264;color:#fff}
#stop{min-width:128px;min-height:64px;background:#a11;color:#fff;font-weight:bold;border:0;font-size:20px}
#mstat{min-width:220px;font-variant-numeric:tabular-nums}
</style></head><body>
<div id="view"></div>
<div id="panel">
<div id="stat">接続中…</div>
<label id="sizebox">解像度 <select id="size"></select></label>
<button id="latency" hidden>遅延を測定</button>
<label><input type="checkbox" id="full"> 等倍表示</label>
<label><input type="checkbox" id="manual"> 手動露出</label>
<label>露出 <input type="range" id="exp" min="0" max="4" step="0.01"> <span id="expv"></span></label>
<label>ゲイン <input type="range" id="gain" min="0" max="128"> <span id="gainv"></span></label>
<div id="err"></div>
<div id="mount">
<div id="pad">
<span></span><button data-axis="alt" data-dir="1">高度 +</button><span></span>
<button data-axis="az" data-dir="-1">方位 −</button><span></span><button data-axis="az" data-dir="1">方位 +</button>
<span></span><button data-axis="alt" data-dir="-1">高度 −</button><span></span>
</div>
<button id="stop">停止</button>
<label>速度 <select id="rate"></select></label>
<div id="mstat"></div>
<div>太陽に向けないでください。押している間だけ動きます。</div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=v=>v>=10000?(v/10000).toFixed(1)+" 秒":(v/10).toFixed(1)+" ms";
const toExp=p=>Math.max(1,Math.round(10**p));
async function send(q){
  const r=await fetch("/control?"+new URLSearchParams(q),{method:"POST"});
  const j=await r.json();
  $("err").textContent=j.error||"";
  return j;
}
function show(s){
  if(!s.webrtc)$("stat").textContent=`${s.size}  ${s.fps.toFixed(1)} fps  フレームサイズ ${(s.frame_bytes/1024).toFixed(0)} KB（ピントが合うほど大きくなる目安）`;
  if(document.activeElement!==$("size"))$("size").value=s.size;
  $("manual").checked=s.manual;
  $("exp").disabled=!s.manual;
  if(document.activeElement!==$("exp"))$("exp").value=Math.log10(s.exposure);
  $("expv").textContent=fmt(s.exposure);
  if(document.activeElement!==$("gain"))$("gain").value=s.gain;
  $("gainv").textContent=s.gain;
}
async function poll(){
  try{show(await (await fetch("/status")).json())}
  catch(e){$("stat").textContent="サーバーに接続できません"}
}
$("full").onchange=e=>$("view").classList.toggle("full",e.target.checked);
$("manual").onchange=e=>send({manual:e.target.checked?1:0}).then(poll);
$("exp").oninput=e=>{$("expv").textContent=fmt(toExp(+e.target.value))};
$("exp").onchange=e=>send({exposure:toExp(+e.target.value)}).then(()=>{e.target.blur();poll()});
$("gain").oninput=e=>{$("gainv").textContent=e.target.value};
$("gain").onchange=e=>send({gain:e.target.value}).then(()=>{e.target.blur();poll()});
$("size").onchange=e=>send({size:e.target.value}).then(()=>{e.target.blur();
  $("img").src="/stream.mjpg?"+Date.now();poll()});
fetch("/sizes").then(r=>r.json()).then(l=>{
  for(const s of l)$("size").add(new Option(s,s));poll();setInterval(poll,1000)});
fetch("/status").then(r=>r.json()).then(s=>{
  if(s.webrtc)startWebrtc(s.webrtc);
  else{const i=new Image();i.id="img";i.alt="カメラ映像";i.src="/stream.mjpg";$("view").append(i)}
});

let pc=null,lastStat=null,latencyNote="";
async function startWebrtc(port){
  $("sizebox").style.display="none";
  $("latency").hidden=false;
  const v=document.createElement("video");
  v.id="video";v.autoplay=v.muted=v.playsInline=true;
  $("view").append(v);
  async function connect(){
    pc=new RTCPeerConnection();
    const t=pc.addTransceiver("video",{direction:"recvonly"});
    if("jitterBufferTarget" in t.receiver)t.receiver.jitterBufferTarget=0;
    pc.ontrack=e=>{v.srcObject=new MediaStream([e.track])};
    const self=pc;
    pc.onconnectionstatechange=()=>{
      if(["failed","disconnected","closed"].includes(self.connectionState)&&self===pc){
        pc.close();setTimeout(()=>connect().catch(retry),2000);
      }
    };
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise(done=>{
      if(pc.iceGatheringState==="complete")return done();
      pc.onicegatheringstatechange=()=>{if(self.iceGatheringState==="complete")done()};
      setTimeout(done,2000);
    });
    const r=await fetch(`http://${location.hostname}:${port}/camera/whep`,
      {method:"POST",headers:{"Content-Type":"application/sdp"},body:pc.localDescription.sdp});
    if(!r.ok)throw new Error("WHEP "+r.status);
    await pc.setRemoteDescription({type:"answer",sdp:await r.text()});
  }
  function retry(e){
    $("stat").textContent="映像に接続できません: "+e.message;
    setTimeout(()=>connect().catch(retry),2000);
  }
  connect().catch(retry);
  setInterval(async()=>{
    if(!pc)return;
    (await pc.getStats()).forEach(r=>{
      if(r.type!=="inbound-rtp"||r.kind!=="video")return;
      const mbps=lastStat?(r.bytesReceived-lastStat.bytes)*8/(r.timestamp-lastStat.time)/1000:0;
      lastStat={bytes:r.bytesReceived,time:r.timestamp};
      $("stat").textContent=`WebRTC ${v.videoWidth}x${v.videoHeight}  ${(r.framesPerSecond||0).toFixed(1)} fps  ${mbps.toFixed(1)} Mbps  欠落 ${r.packetsLost||0}  ${latencyNote}`;
    });
  },1000);
}

// ゲインを大きく変え、映像の明るさが変わるまでの時間を測る。カメラの制御にかかる時間も含む
function brightness(v,c){
  c.drawImage(v,0,0,c.canvas.width,c.canvas.height);
  const d=c.getImageData(0,0,c.canvas.width,c.canvas.height).data;
  let sum=0;
  for(let i=0;i<d.length;i+=4)sum+=d[i+1];
  return sum/(d.length/4);
}
async function waitChange(v,c,before,gain,limit){
  const t0=performance.now();
  send({gain});
  while(performance.now()-t0<limit){
    await new Promise(requestAnimationFrame);
    if(Math.abs(brightness(v,c)-before)>Math.max(2,before*0.15))return performance.now()-t0;
  }
  return null;
}
async function measureLatency(){
  const v=$("video"),c=Object.assign(document.createElement("canvas"),{width:64,height:36}).getContext("2d",{willReadFrequently:true});
  const original=(await (await fetch("/status")).json()).gain;
  const results=[];
  try{
    for(let i=0;i<8;i++){
      const t=await waitChange(v,c,brightness(v,c),i%2?8:128,3000);
      if(t!==null)results.push(t);
      await new Promise(r=>setTimeout(r,1500));
    }
  }finally{
    await send({gain:original});
    poll();
  }
  results.sort((a,b)=>a-b);
  latencyNote=results.length?`遅延 中央値 ${results[results.length>>1].toFixed(0)} ms（${results.length} 回、最小 ${results[0].toFixed(0)}、最大 ${results[results.length-1].toFixed(0)}）`:"遅延を測れません（明るさが変わらない）";
  return latencyNote;
}
$("latency").onclick=measureLatency;

// 押している間だけ移動命令を送り続ける。送信が止まるとホスト側でも停止する
let hold=null;
async function mountPost(path,q){
  const r=await fetch(path+"?"+new URLSearchParams(q||{}),{method:"POST"});
  const j=await r.json();
  if(j.error)$("mstat").textContent=j.error;
}
function release(){
  if(!hold)return;
  clearInterval(hold.timer);
  hold.button.classList.remove("on");
  hold=null;
  mountPost("/mount/stop").catch(()=>{});
}
function press(button){
  release();
  const q={axis:button.dataset.axis,dir:button.dataset.dir,rate:$("rate").value};
  const timer=setInterval(()=>mountPost("/mount/move",{...q,hold:1}).catch(()=>{}),300);
  hold={button,timer};
  button.classList.add("on");
  mountPost("/mount/move",q).catch(()=>{});
}
document.querySelectorAll("#pad button").forEach(b=>{
  b.addEventListener("pointerdown",e=>{e.preventDefault();press(b)});
  b.addEventListener("contextmenu",e=>e.preventDefault());
});
for(const ev of ["pointerup","pointercancel","blur"])window.addEventListener(ev,release);
document.addEventListener("visibilitychange",release);
$("stop").addEventListener("pointerdown",e=>{e.preventDefault();release();mountPost("/mount/stop")});
async function mountPoll(){
  try{
    const r=await fetch("/mount/status");
    if(r.status===404)return;
    const s=await r.json();
    if($("mount").style.display!=="flex"){
      $("mount").style.display="flex";
      for(let i=1;i<=s.max_rate;i++)$("rate").add(new Option(i,i));
      $("rate").value=2;
    }
    const moving=Object.keys(s.moving).join(" ");
    $("mstat").textContent=`方位 ${s.az.toFixed(3)}°（±${s.limits.az}）  高度 ${s.alt.toFixed(3)}°（±${s.limits.alt}）  ${moving?"移動中: "+moving:"停止中"}  ${s.error||s.message}`;
  }catch(e){$("mstat").textContent="状態を取得できません"}
}
mountPoll();setInterval(mountPoll,500);
</script></body></html>
"""

# SPA が動かないときのための最小の停止ページ
STOP_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Mount Stop</title></head>
<body style="margin:0;background:#000"><form method="post" action="/mount/stop">
<button style="width:100vw;height:100vh;background:#a11;color:#fff;font-size:15vw;border:0">停止</button>
</form></body></html>
"""


class Camera:
    """ffmpeg から JPEG を読み、最新フレームを配信スレッドへ渡す。"""

    def __init__(self, device, size):
        self.device = device
        self.size = size
        self.cond = threading.Condition()
        self.frame = None
        self.seq = 0
        self.proc = None
        self.times = []

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def set_size(self, size):
        self.size = size
        proc = self.proc
        if proc:
            proc.terminate()

    def fps(self):
        now = time.monotonic()
        with self.cond:
            recent = [t for t in self.times if now - t < 3]
        return len(recent) / 3

    def _run(self):
        while True:
            self.proc = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-loglevel", "error",
                 "-f", "v4l2", "-input_format", "mjpeg",
                 "-video_size", self.size, "-i", self.device,
                 "-c:v", "copy", "-bsf:v", "mjpeg2jpeg", "-f", "mjpeg", "pipe:1"],
                stdout=subprocess.PIPE)
            self._read(self.proc.stdout)
            self.proc.wait()
            time.sleep(0.5)

    def _read(self, stream):
        buf = bytearray()
        while chunk := stream.read1(1 << 16):
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if end < 0:
                    break
                self._publish(bytes(buf[start:end + 2]))
                del buf[:end + 2]

    def _publish(self, frame):
        now = time.monotonic()
        with self.cond:
            self.frame = frame
            self.seq += 1
            self.times = [t for t in self.times if now - t < 3] + [now]
            self.cond.notify_all()


def ctl_get(device):
    out = subprocess.run(
        ["v4l2-ctl", "-d", device, "-C", "auto_exposure,exposure_time_absolute,gain"],
        capture_output=True, text=True, check=True).stdout
    values = {}
    for line in out.splitlines():
        key, _, value = line.partition(":")
        values[key.strip()] = int(value.split()[0])
    return values


def ctl_set(device, name, value):
    # 複数の項目を 1 回で設定すると順序の都合で拒否されるため、1 項目ずつ設定する
    subprocess.run(["v4l2-ctl", "-d", device, "-c", f"{name}={value}"],
                   capture_output=True, text=True, check=True)


def make_handler(cam, mount, device, webrtc_port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, "application/json", json.dumps(obj).encode())

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode())
            elif path == "/sizes":
                self._json(SIZES)
            elif path == "/status":
                values = ctl_get(device)
                self._json({
                    "webrtc": webrtc_port,
                    "size": cam.size if cam else None, "fps": cam.fps() if cam else 0,
                    "frame_bytes": len(cam.frame or b"") if cam else 0,
                    "manual": values["auto_exposure"] == 1,
                    "exposure": values["exposure_time_absolute"],
                    "gain": values["gain"]})
            elif path in ("/snapshot.jpg", "/stream.mjpg") and not cam:
                self._json({"error": "not available with --webrtc"}, 404)
            elif path == "/snapshot.jpg":
                with cam.cond:
                    frame = cam.frame or (cam.cond.wait(5) and cam.frame)
                if frame:
                    self._send(200, "image/jpeg", frame)
                else:
                    self._json({"error": "no frame"}, 503)
            elif path == "/stream.mjpg":
                self._stream()
            elif path == "/stop" and mount:
                self._send(200, "text/html; charset=utf-8", STOP_PAGE.encode())
            elif path == "/mount/status" and mount:
                self._json(mount.status())
            else:
                self._json({"error": "not found"}, 404)

        def _stream(self):
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            seq = 0
            try:
                while True:
                    with cam.cond:
                        if not cam.cond.wait_for(lambda: cam.seq != seq, timeout=10):
                            continue
                        seq, frame = cam.seq, cam.frame
                    self.wfile.write(
                        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            url = urlparse(self.path)
            if url.path.startswith("/mount/") and mount:
                self._mount_post(url)
                return
            if url.path != "/control":
                self._json({"error": "not found"}, 404)
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if "size" in q:
                    if q["size"] not in SIZES or not cam:
                        raise ValueError("unknown size")
                    cam.set_size(q["size"])
                if "manual" in q:
                    manual = q["manual"] == "1"
                    ctl_set(device, "auto_exposure", 1 if manual else 3)
                if "exposure" in q:
                    value = int(q["exposure"])
                    if not 1 <= value <= 10000:
                        raise ValueError("exposure out of range")
                    ctl_set(device, "exposure_time_absolute", value)
                if "gain" in q:
                    value = int(q["gain"])
                    if not 0 <= value <= 128:
                        raise ValueError("gain out of range")
                    ctl_set(device, "gain", value)
            except (ValueError, subprocess.CalledProcessError) as e:
                self._json({"error": str(e)}, 400)
                return
            self._json({"ok": True})

        def _mount_post(self, url):
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/mount/stop":
                    mount.stop()
                elif url.path == "/mount/move":
                    mount.move(q["axis"], int(q["dir"]), int(q["rate"]), start="hold" not in q)
                else:
                    self._json({"error": "not found"}, 404)
                    return
            except (KeyError, ValueError, MountError) as e:
                self._json({"error": str(e)}, 400)
                return
            self._json({"ok": True})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--size", default=SIZES[0], choices=SIZES)
    parser.add_argument("--webrtc", action="store_true", help="カメラを開かず、MediaMTX の映像を表示する")
    parser.add_argument("--webrtc-port", type=int, default=8889)
    parser.add_argument("--no-mount", action="store_true", help="架台の操作を無効にする")
    parser.add_argument("--max-rate", type=int, default=6, choices=range(1, 10))
    parser.add_argument("--az-limit", type=float, default=90.0, help="起動時からの方位の範囲（度）")
    parser.add_argument("--alt-limit", type=float, default=45.0, help="起動時からの高度の範囲（度）")
    args = parser.parse_args()

    cam = None
    if not args.webrtc:
        cam = Camera(args.device, args.size)
        cam.start()
    mount = None
    ports = glob.glob("/dev/serial/by-id/*Serial*")
    if not args.no_mount and ports:
        mount = Mount(ports[0], args.max_rate, args.az_limit, args.alt_limit)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(cam, mount, args.device, args.webrtc_port if args.webrtc else None))
    server.daemon_threads = True
    print(f"http://0.0.0.0:{args.port}/ mount={'on' if mount else 'off'}", flush=True)
    try:
        server.serve_forever()
    finally:
        # systemctl stop や Ctrl-C でも架台を止めてから終わる
        if mount:
            mount.close()


if __name__ == "__main__":
    main()
