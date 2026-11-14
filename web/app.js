"use strict";
const $ = id => document.getElementById(id);

const ICONS = {
  plug: '<path d="M7 12l5 5M9 10l5 5M6 18l-3 3M18 6l3-3M8 9l7 7-2 2a4.9 4.9 0 0 1-7-7zM16 15L9 8l2-2a4.9 4.9 0 0 1 7 7z"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  idle: '<circle cx="12" cy="12" r="9"/><rect x="9" y="9" width="6" height="6"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 11l5-3v8l-5-3"/>',
  timelapse: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  still: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  battery: level => `<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/>` +
    Array.from({length: level}, (_, i) => `<path d="M${6 + i * 4} 10.5v3"/>`).join(""),
};
const RECORDING = {
  none: ["idle", "録画なし", "idle"],
  video: ["video", "動画 録画中", "bad"],
  timelapse: ["timelapse", "タイムラプス", "bad"],
  still: ["still", "静止画撮影", "bad"],
};
const POWER = {ok: [3, "電源 OK", "ok"], half: [2, "電源 半分", "warn"], low: [1, "残り僅か", "bad"]};

let latest = null;
let wsOpen = false;

function recordingLabel(r) {
  const base = RECORDING[r.kind] || RECORDING.none;
  return r.kind === "timelapse" ? [base[0], `撮影中 ${r.count || 0} 枚`, base[2]] : base;
}

function stateHtml(icon, label, tone) {
  return `<div class="state" style="color:var(--${tone})"><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>${label}</div>`;
}

function trackingNotice(t) {
  if (!t.target) return t.synscan === "altaz" ? `SynScan が${t.synscan_label || ""}追尾中` : "";
  const g = t.guide;
  const state = {off: "", starting: "（補正の準備中）", waiting: "（映像を待っています）", paused: "（補正は一時停止）", lost: "（模様を見失い、補正を保留）"}[g.state];
  if (state !== undefined) return `${t.label}を追尾中${state}`;
  const seconds = g.error_x === null ? "" : `ずれ ${g.error_x.toFixed(0)}", ${g.error_y.toFixed(0)}"  `;
  return `${t.label}を追尾中  ${seconds}補正 ${g.correction.az.toFixed(2)}, ${g.correction.alt.toFixed(2)}"/秒`;
}

function render() {
  let system;
  if (!wsOpen) system = ["サーバー 切断", "bad"];
  else if (!latest) system = ["確認中", "idle"];
  else if (latest.mount_connection === "disconnected")
    system = latest.system.camera ? ["架台 切断中", "warn"] : ["カメラ 異常", "bad"];
  else if (latest.system.ok) system = ["接続 正常", "ok"];
  else if (!latest.system.mount && !latest.system.camera) system = ["接続 異常", "bad"];
  else system = [latest.system.mount ? "カメラ 異常" : "架台 異常", "bad"];

  // 切断中は古い状態を正しい値のように見せない
  const live = wsOpen && latest;
  const aligned = live && latest.alignment;
  const rec = recordingLabel(live ? latest.recording : {kind: "none"});
  const power = POWER[live ? latest.power : "ok"] || POWER.ok;
  $("status").innerHTML =
    stateHtml(ICONS.plug, system[0], system[1]) +
    (live ? stateHtml(ICONS.target, aligned ? (aligned.source === "synscan" ? "SynScan アライン済" : "アライン済") : "未アライン", aligned ? "ok" : "warn")
          : stateHtml(ICONS.target, "不明", "idle")) +
    (live ? stateHtml(ICONS[rec[0]], rec[1], rec[2]) : stateHtml(ICONS.idle, "不明", "idle")) +
    (live ? stateHtml(ICONS.battery(power[0]), power[1], power[2]) : stateHtml(ICONS.battery(0), "不明", "idle"));

  const p = live && latest.pointing;
  $("pointing").textContent = `方角 ${p ? p.az.toFixed(1) + "°" : "—"}　仰角 ${p ? p.alt.toFixed(1) + "°" : "—"}`;

  const link = live ? latest.mount_connection : null;
  const linkButton = $("mount-link");
  linkButton.textContent = {connected: "架台 接続中", connecting: "架台 接続待ち", disconnected: "架台 切断中"}[link] || "架台 —";
  linkButton.className = link === "disconnected" ? "off" : link === "connected" ? "on" : "";
  linkButton.disabled = !live;

  const mount = live && latest.mount;
  let notice = "";
  if (!wsOpen) notice = "サーバーに再接続しています";
  else if (link === "disconnected") notice = "架台との接続を切っています。SynScan を手元で操作できます";
  else if (mount && mount.error) notice = "架台の通信エラー: " + mount.error;
  else if (live && latest.notice) notice = latest.notice;
  else if (mount && mount.goto) notice = `${mount.goto.label}へ自動導入中  方位 ${mount.goto.progress.toFixed(1)}° / ${mount.goto.plan.az_amount.toFixed(1)}°`;
  else if (live && latest.tracking && trackingNotice(latest.tracking)) notice = trackingNotice(latest.tracking);
  else if (live && latest.recording.message) notice = latest.recording.message;
  else if (live) notice = "太陽に向けないでください";
  $("notice").textContent = notice;

  // 保存の応答を待つ間は、古い位置に戻さない
  if (live && latest.finder && !finderPointPending &&
      (latest.finder.x !== finderPoint.x || latest.finder.y !== finderPoint.y)) {
    finderPoint = latest.finder;
    showFinderPoint();
  }
  if (live && cameraControls()) showCamera(cameraControls());
  if (live) showCapture(latest.recording);
}

// パネルは触れると不透明になる。操作できるのは一度に 1 つだけ
let active = null, activeTimer = 0;
function activate(panel) {
  if (active && active !== panel) {
    active.classList.remove("active");
    if (active.classList.contains("dialog")) active.hidden = true;
  }
  active = panel;
  clearTimeout(activeTimer);
  if (!panel) return;
  panel.classList.add("active");
  if (!panel.classList.contains("dialog")) activeTimer = setTimeout(() => activate(null), 5000);
}
for (const panel of document.querySelectorAll(".panel")) {
  panel.addEventListener("pointerdown", () => activate(panel));
}
$("views").addEventListener("pointerdown", () => activate(null));

// 状態の WebSocket。切れたら接続し直し、最初の受信で現在の状態を受け取る
let ws = null;
function connectStatus() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/api/ws`);
  ws.onopen = () => { wsOpen = true; render(); };
  ws.onmessage = e => {
    const message = JSON.parse(e.data);
    if (message.type === "status") {
      latest = message;
      startVideo(message.webrtc_port, message.recording.stream_epoch);
      render();
    } else if (message.type === "error") {
      $("notice").textContent = message.message;
    }
  };
  ws.onclose = () => {
    wsOpen = false;
    latest = null;
    releaseStick(false);
    render();
    setTimeout(connectStatus, 1500);
  };
}

// 映像は MediaMTX から WebRTC で受ける。主鏡は camera、ファインダーは finder
let videoPort = null, videoEpoch = null;
const streams = {
  camera: {video: $("video"), view: $("view-main"), pc: null, timer: 0},
  finder: {video: $("finder-video"), view: $("view-finder"), pc: null, timer: 0},
};
function startVideo(port, epoch) {
  // 撮影の切り替えで映像の送り主が替わったら、切断の検知を待たずにつなぎ直す
  if (videoPort && epoch === videoEpoch) return;
  const first = !videoPort;
  videoPort = port;
  videoEpoch = epoch;
  // ファインダーは撮影で送り主が替わらないので、最初の 1 回だけつなぐ
  if (first) openStream("finder");
  openStream("camera");
}
function openStream(name) {
  const s = streams[name];
  if (s.pc) s.pc.close();
  clearTimeout(s.timer);
  connectVideo(name).catch(() => retryVideo(name));
}
function retryVideo(name) {
  const s = streams[name];
  s.view.classList.add("offline");
  clearTimeout(s.timer);
  s.timer = setTimeout(() => connectVideo(name).catch(() => retryVideo(name)), 1000);
}
async function connectVideo(name) {
  const s = streams[name];
  const conn = s.pc = new RTCPeerConnection();
  const transceiver = conn.addTransceiver("video", {direction: "recvonly"});
  if ("jitterBufferTarget" in transceiver.receiver) transceiver.receiver.jitterBufferTarget = 0;
  conn.ontrack = e => {
    if (conn !== s.pc) return;
    s.video.srcObject = new MediaStream([e.track]);
    s.view.classList.remove("offline");
  };
  conn.onconnectionstatechange = () => {
    if (conn === s.pc && ["failed", "closed", "disconnected"].includes(conn.connectionState)) {
      conn.close();
      retryVideo(name);
    }
  };
  try {
    await conn.setLocalDescription(await conn.createOffer());
    await new Promise(done => {
      if (conn.iceGatheringState === "complete") return done();
      conn.onicegatheringstatechange = () => { if (conn.iceGatheringState === "complete") done(); };
      setTimeout(done, 2000);
    });
    const r = await fetch(`/api/whep/${name}`,
      {method: "POST", headers: {"Content-Type": "application/sdp"}, body: conn.localDescription.sdp});
    if (conn !== s.pc) { conn.close(); return; }
    if (!r.ok) throw new Error("WHEP " + r.status);
    await conn.setRemoteDescription({type: "answer", sdp: await r.text()});
  } catch (e) {
    conn.close();
    if (conn === s.pc) throw e;
  }
}
// 枠の縦横比を映像に合わせる。タイムラプス中の主鏡は 1632×1080 になる
for (const s of Object.values(streams)) {
  s.video.addEventListener("resize", () => {
    if (s.video.videoWidth) s.view.querySelector(".frame").style.setProperty("--ar", `${s.video.videoWidth} / ${s.video.videoHeight}`);
  });
}

// 表示の切り替え。ワイプに触ると大小を入れ替える
const VIEW_ORDER = ["main", "split", "finder"];
const VIEW_LABEL = {main: "表示: 主鏡", split: "表示: 横並び", finder: "表示: ファインダー"};
const ZOOMS = [1, 2, 4, 8];
const saved = key => { try { return localStorage.getItem(key); } catch (e) { return null; } };
const save = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* 保存できなくても表示は続ける */ } };
let viewMode = VIEW_ORDER.includes(saved("view")) ? saved("view") : "main";
let finderZoom = ZOOMS.includes(+saved("finderZoom")) ? +saved("finderZoom") : 1;
let finderPoint = {x: 0.5, y: 0.5}, finderPointPending = false, placing = false;

function setView(mode) {
  viewMode = mode;
  save("view", mode);
  $("views").dataset.view = mode;
  $("view-mode").textContent = VIEW_LABEL[mode];
  // ファインダーの道具は、ファインダーが大きく見えているときだけ出す
  $("finder-tools").hidden = mode === "main";
  if (mode === "main") setPlacing(false);
}
function showFinderPoint() {
  const {x, y} = finderPoint;
  const reticle = $("finder-reticle");
  reticle.style.left = `${x * 100}%`;
  reticle.style.top = `${y * 100}%`;
  // 照準を中心に拡大するので、照準の下の景色は拡大しても動かない
  const zoom = $("finder-zoom");
  zoom.style.transformOrigin = `${x * 100}% ${y * 100}%`;
  zoom.style.transform = finderZoom === 1 ? "" : `scale(${finderZoom})`;
  $("finder-zoom-button").textContent = `×${finderZoom}`;
}
function setPlacing(on) {
  placing = on;
  $("finder-place").classList.toggle("on", on);
  $("views").classList.toggle("placing", on);
}
// 枠の中の位置を 0〜1 の割合で返す。縦持ちでは画面全体を 90° 回しているので、画面の座標を戻す
function framePosition(frame, e) {
  const rect = frame.getBoundingClientRect();
  if (window.matchMedia("(orientation: portrait)").matches) {
    return {x: (e.clientY - rect.top) / rect.height, y: (rect.right - e.clientX) / rect.width};
  }
  return {x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height};
}
async function saveFinderPoint(point) {
  finderPoint = point;
  finderPointPending = true;
  showFinderPoint();
  try {
    const body = await (await postJson("/api/finder", point)).json();
    if (body.error) $("notice").textContent = body.error;
  } catch (e) { $("notice").textContent = "照準の位置を保存できません"; }
  finderPointPending = false;
}
for (const [view, mode] of [[$("view-main"), "main"], [$("view-finder"), "finder"]]) {
  view.addEventListener("pointerdown", e => {
    const wipe = viewMode !== "split" && viewMode !== mode;
    if (wipe) { setView(mode); return; }
    if (!placing || mode !== "finder") return;
    // 拡大中は、照準を中心にした拡大を戻して映像の上の位置に直す
    const f = framePosition(view.querySelector(".frame"), e);
    if (f.x < 0 || f.x > 1 || f.y < 0 || f.y > 1) return;
    const clamp = v => Math.min(1, Math.max(0, v));
    saveFinderPoint({x: clamp(finderPoint.x + (f.x - finderPoint.x) / finderZoom),
                     y: clamp(finderPoint.y + (f.y - finderPoint.y) / finderZoom)});
  });
}
$("view-mode").addEventListener("click", () => setView(VIEW_ORDER[(VIEW_ORDER.indexOf(viewMode) + 1) % VIEW_ORDER.length]));
$("finder-zoom-button").addEventListener("click", () => {
  finderZoom = ZOOMS[(ZOOMS.indexOf(finderZoom) + 1) % ZOOMS.length];
  save("finderZoom", finderZoom);
  showFinderPoint();
});
$("finder-place").addEventListener("click", () => setPlacing(!placing));
$("finder-reset").addEventListener("click", () => saveFinderPoint({x: 0.5, y: 0.5}));
setView(viewMode);
showFinderPoint();

// スティック。倒す向きでパンとティルトの割合が、倒す量で速度が決まる
const STICK_CURVE = 1.8, DEAD_ZONE = 0.12, SEND_INTERVAL = 200;
let stickPointer = null, stickValue = {az: 0, alt: 0}, stickTimer = 0;
const stick = $("stick"), knob = $("knob");

function sendStick() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: "stick", az: stickValue.az, alt: stickValue.alt}));
  }
}
function axisRate(v) {
  // 小さく倒す範囲を広く取り、微動と高速移動を両立する
  const maxRate = latest && latest.mount ? latest.mount.max_rate : 1;
  return Math.abs(v) < DEAD_ZONE ? 0 : Math.sign(v) * Math.ceil(((Math.abs(v) - DEAD_ZONE) / (1 - DEAD_ZONE)) ** STICK_CURVE * maxRate);
}
function moveStick(e) {
  const rect = stick.getBoundingClientRect();
  let dx = e.clientX - (rect.left + rect.width / 2);
  let dy = e.clientY - (rect.top + rect.height / 2);
  // 縦持ちでは画面全体を 90° 回しているので、画面の座標を戻す
  if (window.matchMedia("(orientation: portrait)").matches) [dx, dy] = [dy, -dx];
  const reach = (stick.offsetWidth - knob.offsetWidth) / 2;
  const length = Math.hypot(dx, dy);
  if (length > reach) { dx *= reach / length; dy *= reach / length; }
  knob.style.transform = `translate(${dx}px, ${dy}px)`;
  const next = {az: axisRate(dx / reach), alt: axisRate(-dy / reach)};
  const changed = next.az !== stickValue.az || next.alt !== stickValue.alt;
  stickValue = next;
  if (changed) sendStick();
}
function releaseStick(notify = true) {
  if (stickPointer === null) return;
  stickPointer = null;
  clearInterval(stickTimer);
  knob.style.transform = "";
  stickValue = {az: 0, alt: 0};
  if (notify) sendStick();
}
stick.addEventListener("pointerdown", e => {
  e.preventDefault();
  stick.setPointerCapture(e.pointerId);
  stickPointer = e.pointerId;
  moveStick(e);
  // 同じ値でも送り続ける。止まるとホスト側で架台を止める
  stickTimer = setInterval(sendStick, SEND_INTERVAL);
});
stick.addEventListener("pointermove", e => { if (e.pointerId === stickPointer) moveStick(e); });
for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
  stick.addEventListener(type, e => { if (e.pointerId === stickPointer) releaseStick(); });
}
window.addEventListener("blur", () => releaseStick());
document.addEventListener("visibilitychange", () => releaseStick());
stick.addEventListener("contextmenu", e => e.preventDefault());

// 停止は WebSocket に頼らず送る
$("stop").addEventListener("pointerdown", e => {
  e.preventDefault();
  releaseStick();
  fetch("/api/mount/stop", {method: "POST"}).then(async r => {
    const body = await r.json();
    if (body.error) $("notice").textContent = body.error;
  }).catch(() => { $("notice").textContent = "停止を送れません。架台の電源を切ってください"; });
});

// 架台との接続の切り替え。切ると架台を止めてシリアルを手放す（映像はそのまま）
$("mount-link").addEventListener("click", async () => {
  const connect = latest && latest.mount_connection === "disconnected";
  const message = connect
    ? "架台に接続します。接続すると架台を止めます。SynScan で動かしていないことを確かめてください。"
    : "架台との接続を切ります。動いていれば止めてから切ります。切っている間は、この画面から架台を操作できません。";
  if (!confirm(message)) return;
  releaseStick();
  try {
    const r = await fetch("/api/mount/connection", {method: "POST", headers: {"Content-Type": "application/json"},
                                                    body: JSON.stringify({connected: connect})});
    const body = await r.json();
    if (body.error) $("notice").textContent = body.error;
  } catch {
    $("notice").textContent = "接続の切り替えを送れませんでした";
  }
});

// カメラのダイアログ
const formatExposure = v => v >= 10000 ? (v / 10000).toFixed(1) + " 秒" : (v / 10).toFixed(1) + " ms";
const toExposure = p => Math.max(1, Math.round(10 ** p));
// 指で触っている間だけ、スライダーを操作中として扱う。タッチでは :active が当てにならず、
// ダイアログを閉じたときのフォーカス移動でも change が届くことがあるので、触っていない change は送らない
const sliderEditing = new Set();
for (const id of ["exposure", "gain"]) {
  const slider = $(id);
  const begin = () => sliderEditing.add(id);
  const end = () => setTimeout(() => sliderEditing.delete(id), 300);
  slider.addEventListener("pointerdown", begin);
  slider.addEventListener("keydown", begin);
  slider.addEventListener("pointerup", end);
  slider.addEventListener("pointercancel", end);
  slider.addEventListener("keyup", end);
}
// 主鏡とファインダーで同じダイアログを使う。ホストは主鏡を camera、ファインダーを finder_camera で返す
let cameraTarget = "camera";
const CAMERA_API = {camera: "/api/camera", finder: "/api/finder/camera"};
function cameraControls() {
  return latest && latest[cameraTarget === "finder" ? "finder_camera" : "camera"];
}
function setCameraTarget(target) {
  cameraTarget = target;
  for (const b of document.querySelectorAll("[data-camera]")) b.classList.toggle("on", b.dataset.camera === target);
  sliderEditing.clear();
  const c = cameraControls();
  if (c) showCamera(c);
}
function showCamera(c) {
  $("exposure").max = Math.log10(c.exposure_max);
  $("gain").max = c.gain_max;
  if (document.activeElement !== $("manual")) $("manual").checked = c.manual;
  $("exposure").disabled = !c.manual;
  if (!sliderEditing.has("exposure")) {
    $("exposure").value = Math.log10(c.exposure);
    $("exposure-value").textContent = formatExposure(c.exposure);
  }
  if (!sliderEditing.has("gain")) {
    $("gain").value = c.gain;
    $("gain-value").textContent = c.gain;
  }
}
async function setCamera(values) {
  const r = await fetch(CAMERA_API[cameraTarget], {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
  const body = await r.json();
  if (body.error) $("notice").textContent = body.error;
}
function openCamera(target) {
  setCameraTarget(target);
  $("camera").hidden = false;
  activate($("camera"));
}
// ファインダーを大きく出しているときは、ファインダーの設定から開く
$("open-camera").addEventListener("click", () => openCamera(viewMode === "finder" ? "finder" : "camera"));
$("finder-camera").addEventListener("click", () => openCamera("finder"));
for (const b of document.querySelectorAll("[data-camera]")) b.addEventListener("click", () => setCameraTarget(b.dataset.camera));
$("close-camera").addEventListener("click", () => activate(null));
$("manual").addEventListener("change", e => setCamera({manual: e.target.checked}));
$("exposure").addEventListener("input", e => { if (sliderEditing.has("exposure")) $("exposure-value").textContent = formatExposure(toExposure(+e.target.value)); });
$("exposure").addEventListener("change", e => {
  if (!sliderEditing.has("exposure")) return;
  setCamera({exposure: toExposure(+e.target.value)});
  e.target.blur();
});
$("gain").addEventListener("input", e => { if (sliderEditing.has("gain")) $("gain-value").textContent = e.target.value; });
$("gain").addEventListener("change", e => {
  if (!sliderEditing.has("gain")) return;
  setCamera({gain: +e.target.value});
  e.target.blur();
});

// アラインメントのダイアログ。計算した位置と、現在の向きとの差を表示する
const signed = v => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "°";
async function refreshAlign() {
  if ($("align").hidden) return;
  try {
    const r = await (await fetch("/api/alignment")).json();
    const a = r.alignment;
    $("align-state").textContent = `観測地 ${r.site.latitude.toFixed(5)}° ${r.site.longitude.toFixed(5)}°（${SITE_SOURCE[r.site.source] || ""}）　` +
      (!a ? "未登録"
        : a.source === "synscan" ? "SynScan 本体のアライメントを使用中（架台の値をそのまま表示）"
        : `${new Date(a.time * 1000).toLocaleTimeString()} に ${a.star === "polaris" ? "北極星" : a.star} で登録済み`);
    $("targets").innerHTML = `<tr><th>天体</th><th>方角</th><th>仰角</th><th>方角の差</th><th>仰角の差</th></tr>` +
      r.targets.map(t => `<tr><td>${t.label}</td><td>${t.az.toFixed(2)}°</td><td>${t.alt.toFixed(2)}°</td>` +
        `<td>${t.daz === undefined ? "—" : signed(t.daz)}</td><td>${t.dalt === undefined ? "—" : signed(t.dalt)}</td></tr>`).join("");
  } catch (e) { $("align-state").textContent = "サーバーに接続できません"; }
}
setInterval(refreshAlign, 2000);
$("open-align").addEventListener("click", () => { $("align").hidden = false; activate($("align")); refreshAlign(); loadSite(); });
$("close-align").addEventListener("click", () => { stopMeasure(); activate(null); });

// 観測地。入力欄は開いたときと保存したときだけ埋め、入力中の値を定期更新で消さない
const SITE_SOURCE = {config: "設定ファイル", phone: "端末の位置", map: "地図", manual: "手入力"};
let siteMeasured = null, siteAdopted = null, savedSite = null, measureWatch = null, measureTimer = null;
const BREAKDOWN = {ground_m: "site-ground", height_m: "site-height", geoid_m: "site-geoid"};
function fillSite(site) {
  $("site-lat").value = site.latitude.toFixed(6);
  $("site-lon").value = site.longitude.toFixed(6);
  $("site-elev").value = site.elevation_m.toFixed(1);
  for (const [key, id] of Object.entries(BREAKDOWN)) $(id).value = site[key] === undefined ? "" : site[key];
}
// 地面、高さ、ジオイド高がそろったら、標高（楕円体高）はその合計にする
const fieldNumber = id => $(id).value.trim() === "" ? null : +$(id).value;
function updateElevation() {
  const parts = Object.values(BREAKDOWN).map(fieldNumber);
  if (parts.every(v => v !== null && isFinite(v))) $("site-elev").value = parts.reduce((a, b) => a + b, 0).toFixed(1);
}
for (const id of Object.values(BREAKDOWN)) $(id).addEventListener("input", updateElevation);
async function loadSite() {
  try {
    const site = await (await fetch("/api/site")).json();
    fillSite(site);
    siteMeasured = siteAdopted = null;
    savedSite = site;
    $("site-state").textContent = site.time
      ? `${new Date(site.time * 1000).toLocaleString()} に${SITE_SOURCE[site.source]}で保存` +
        (site.accuracy_m ? `（誤差 約 ${site.accuracy_m.toFixed(0)} m）` : "")
      : "まだ保存していません（SynScan の既定値）";
  } catch (e) { $("site-state").textContent = "サーバーに接続できません"; }
}
function stopMeasure() {
  if (measureWatch !== null) navigator.geolocation.clearWatch(measureWatch);
  clearTimeout(measureTimer);
  measureWatch = null;
  $("site-measure").textContent = "この端末の位置を測る";
}
// 30 秒間の測位を集め、誤差の小さいものを誤差の 2 乗の逆数で重み付けして平均する
const MEASURE_SECONDS = 30;
function summarize(samples) {
  const best = Math.min(...samples.map(p => p.accuracy));
  const good = samples.filter(p => p.accuracy <= best * 2);
  const w = good.map(p => 1 / (p.accuracy * p.accuracy));
  const sum = w.reduce((a, b) => a + b, 0);
  const mean = key => good.reduce((a, p, i) => a + p[key] * w[i], 0) / sum;
  const heights = good.filter(p => p.altitude !== null);
  return {latitude: mean("latitude"), longitude: mean("longitude"), accuracy: best, count: good.length,
          altitude: heights.length ? heights.reduce((a, p) => a + p.altitude, 0) / heights.length : null,
          altitudeAccuracy: heights.length ? Math.min(...heights.map(p => p.altitudeAccuracy ?? Infinity)) : null};
}
$("site-measure").addEventListener("click", () => {
  if (measureWatch !== null) { stopMeasure(); return; }
  if (!window.isSecureContext || !navigator.geolocation) {
    $("site-state").textContent = "位置情報は HTTPS で開いたときだけ使えます";
    return;
  }
  const samples = [];
  const started = Date.now();
  $("site-state").textContent = "測位を待っています…（位置情報の許可を求められたら許可してください）";
  $("site-measure").textContent = "測るのをやめる";
  measureWatch = navigator.geolocation.watchPosition(pos => {
    const c = pos.coords;
    samples.push({latitude: c.latitude, longitude: c.longitude, accuracy: c.accuracy,
                  altitude: c.altitude, altitudeAccuracy: c.altitudeAccuracy});
    siteMeasured = summarize(samples);
    $("site-lat").value = siteMeasured.latitude.toFixed(6);
    $("site-lon").value = siteMeasured.longitude.toFixed(6);
    const left = Math.max(0, MEASURE_SECONDS - Math.round((Date.now() - started) / 1000));
    $("site-state").textContent = `測位 ${samples.length} 回、誤差 約 ${siteMeasured.accuracy.toFixed(0)} m` +
      (siteMeasured.altitude !== null ? `、端末の高度 ${siteMeasured.altitude.toFixed(0)} m` +
        (siteMeasured.altitudeAccuracy && isFinite(siteMeasured.altitudeAccuracy) ? `（±${siteMeasured.altitudeAccuracy.toFixed(0)} m、参考）` : "（参考）") : "") +
      (left ? `　残り ${left} 秒` : "　完了。保存すると反映されます");
  }, err => {
    stopMeasure();
    $("site-state").textContent = err.code === err.PERMISSION_DENIED
      ? "位置情報が許可されていません。ブラウザのサイト設定で許可してください" : `測位できません（${err.message}）`;
  }, {enableHighAccuracy: true, maximumAge: 0, timeout: 60000});
  measureTimer = setTimeout(stopMeasure, MEASURE_SECONDS * 1000);
});
$("site-save").addEventListener("click", async () => {
  if (["site-lat", "site-lon", "site-elev"].some(id => $(id).value.trim() === "")) {
    $("site-state").textContent = "緯度、経度、標高をすべて入力してください";
    return;
  }
  // 地理院の値だけ入って高さが空のまま保存すると、標高が地面より低い値になる
  if (fieldNumber("site-ground") !== null && fieldNumber("site-geoid") !== null && fieldNumber("site-height") === null) {
    $("site-state").textContent = "地面から望遠鏡までの高さを入れてください";
    return;
  }
  const lat = +$("site-lat").value, lon = +$("site-lon").value;
  // 地図で採用した点や測った値をそのまま保存したときだけ、その出どころを残す
  const same = p => p && lat.toFixed(6) === p.latitude.toFixed(6) && lon.toFixed(6) === p.longitude.toFixed(6);
  const fromMap = same(siteAdopted), fromPhone = !fromMap && same(siteMeasured);
  // 高さだけ直して保存し直したときは、保存済みの出どころを引き継ぐ
  const keep = !fromMap && !fromPhone && same(savedSite) && ["map", "phone"].includes(savedSite.source);
  stopMeasure();
  const body = {latitude: lat, longitude: lon, elevation_m: +$("site-elev").value,
                source: fromMap ? "map" : fromPhone ? "phone" : keep ? savedSite.source : "manual"};
  if (fromPhone) body.accuracy_m = siteMeasured.accuracy;
  else if (keep && savedSite.accuracy_m !== undefined) body.accuracy_m = savedSite.accuracy_m;
  for (const [key, id] of Object.entries(BREAKDOWN)) if (fieldNumber(id) !== null) body[key] = fieldNumber(id);
  const r = await (await postJson("/api/site", body)).json();
  if (r.error) { $("site-state").textContent = r.error; return; }
  await loadSite();
  refreshAlign();
});
$("register").addEventListener("click", async () => {
  const r = await fetch("/api/alignment/register", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({star: "polaris"})});
  const body = await r.json();
  if (body.error) $("align-state").textContent = body.error;
  else refreshAlign();
});
$("clear-align").addEventListener("click", async () => {
  await fetch("/api/alignment", {method: "DELETE"});
  refreshAlign();
});

// 撮影のダイアログ。状態はホストが持ち、ここでは表示と指示だけを行う
const postJson = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
const REC_NAMES = {none: "待機中", still: "静止画を撮影中", timelapse: "タイムラプス撮影中", video: "動画を記録中"};
let previewSeq = 0, lastKind = "none";
function showCapture(r) {
  const busy = r.kind !== "none";
  for (const id of ["shoot-still", "shoot-timelapse", "shoot-video"]) $(id).disabled = busy;
  $("shoot-stop").disabled = r.kind !== "timelapse" && r.kind !== "video";
  const parts = [REC_NAMES[r.kind] || r.kind];
  if (r.kind === "timelapse") parts.push(`${r.count || 0} 枚、${r.interval} 秒間隔`);
  if (r.kind === "video") parts.push(`上限 ${r.seconds} 秒、経過 ${Math.round(latest.time - r.started_at)} 秒`);
  if (r.free_gb != null) parts.push(`空き ${r.free_gb.toFixed(0)} GB`);
  $("capture-state").textContent = parts.join("　");
  if (r.preview_seq && r.preview_seq !== previewSeq && !$("capture").hidden) {
    previewSeq = r.preview_seq;
    $("capture-preview").src = `/api/capture/preview?seq=${previewSeq}`;
    $("capture-preview").hidden = false;
  }
  if (lastKind !== r.kind) {
    lastKind = r.kind;
    refreshCaptures();
  }
}
const formatSize = n => n >= 1e9 ? (n / 1e9).toFixed(1) + " GB" : (n / 1e6).toFixed(1) + " MB";
async function refreshCaptures() {
  if ($("capture").hidden) return;
  try {
    const {sessions} = await (await fetch("/api/captures")).json();
    const table = $("capture-list");
    table.textContent = "";
    for (const s of sessions) {
      const row = table.insertRow();
      row.insertCell().textContent = s.path;
      row.insertCell().textContent = `${s.files} 件`;
      row.insertCell().textContent = formatSize(s.size);
      if (s.latest) {
        const link = document.createElement("a");
        link.href = `/captures/${s.path}/${s.latest}`;
        link.target = "_blank";
        link.textContent = "最新";
        row.insertCell().append(link);
      }
    }
  } catch (e) { /* 再接続後の状態の更新で読み直す */ }
}
async function shoot(path, values) {
  try {
    const r = await postJson(path, {target: $("capture-target").value, ...values});
    const body = await r.json();
    if (body.error) showCaptureMessage(body.error);
  } catch (e) { showCaptureMessage("サーバーに接続できません"); }
}
// 状態の行は更新で上書きされるので、知らせは OK を押すまで別の枠に残す
function showCaptureMessage(text) {
  $("capture-message-text").textContent = text;
  $("capture-message").hidden = false;
}
// タイムラプスと動画は露出を固定して撮るので、自動露出のままなら何もしない
function shootManual(path, values) {
  if (latest && latest.camera && !latest.camera.manual) {
    showCaptureMessage("露出が自動です。「カメラ設定」から手動にして露出を合わせてください");
    return;
  }
  shoot(path, values);
}
$("capture-message-ok").addEventListener("click", () => { $("capture-message").hidden = true; });
// 天体の導入と追尾。名前か赤経・赤緯で調べ、計画を確かめてから導入し、追尾する
let trackTarget = null, trackTimer = 0, gotoPlanId = null;
function fmtDeg(v, sign) { return (sign && v >= 0 ? "+" : "") + v.toFixed(2) + "°"; }
function showTrackInfo(t) {
  const info = $("track-info");
  info.classList.toggle("error", !!t.error);
  if (t.error) { info.textContent = t.error; return; }
  const diff = t.daz === undefined ? "" : `\n今の向きとの差  方位 ${fmtDeg(t.daz, true)}  高度 ${fmtDeg(t.dalt, true)}`;
  info.textContent = (t.kind === "coords" ? `指定の位置（${t.radec}、J2000）\n` : `${t.label}（${t.radec}、J2000）\n`) +
    `今  方位 ${t.az.toFixed(2)}°  高度 ${t.alt.toFixed(2)}°${t.above ? "" : "（地平線の下）"}` +
    `  動き ${t.rates.az.toFixed(1)}", ${t.rates.alt.toFixed(1)}"/秒` + diff;
}
function selectTrack(query) {
  trackTarget = query;
  hidePlan();
  for (const b of $("track-quick").children) b.classList.toggle("on", b.dataset.key === query);
  refreshTrackInfo();
}
async function refreshTrackInfo() {
  clearTimeout(trackTimer);
  if (!trackTarget || $("track").hidden) return;
  let t;
  try { t = await (await fetch(`/api/sky/lookup?q=${encodeURIComponent(trackTarget)}`)).json(); }
  catch (e) { t = {error: "サーバーに接続できません"}; }
  showTrackInfo(t);
  $("goto-plan").disabled = $("track-start").disabled = !!t.error || !t.above;
  trackTimer = setTimeout(refreshTrackInfo, 2000);
}
function hidePlan() { $("track-plan").hidden = true; gotoPlanId = null; }
function showPlanError(text) {
  $("track-plan").hidden = false;
  $("track-plan-text").textContent = text;
  $("track-plan-text").classList.add("error");
  $("goto-run").hidden = true;
}
async function loadQuickTargets() {
  try {
    const r = await (await fetch("/api/sky/catalog")).json();
    $("track-quick").textContent = "";
    for (const t of r.quick) {
      const b = document.createElement("button");
      b.textContent = t.label;
      b.dataset.key = t.key;
      b.addEventListener("click", () => { $("track-query").value = ""; selectTrack(t.key); });
      $("track-quick").append(b);
    }
  } catch (e) { /* 開き直したときに読み直す */ }
}
$("open-track").addEventListener("click", () => {
  $("track").hidden = false; activate($("track"));
  if (!$("track-quick").children.length) loadQuickTargets();
  refreshTrackInfo();
});
$("close-track").addEventListener("click", () => { hidePlan(); activate(null); });
$("track-lookup").addEventListener("click", () => { if ($("track-query").value.trim()) selectTrack($("track-query").value.trim()); });
$("track-query").addEventListener("keydown", e => { if (e.key === "Enter") $("track-lookup").click(); });
$("goto-plan").addEventListener("click", async () => {
  if (!trackTarget) return;
  hidePlan();
  try {
    const r = await (await postJson("/api/goto/plan", {target: trackTarget})).json();
    if (r.error) { showPlanError(r.error); return; }
    gotoPlanId = r.plan_id;
    $("track-plan").hidden = false;
    $("track-plan-text").classList.remove("error");
    $("track-plan-text").textContent = `${r.plan.label}へ: ${r.text}。動き出したら停止ボタンでいつでも止められます。`;
    $("goto-run").hidden = false;
  } catch (e) { showPlanError("サーバーに接続できません"); }
});
$("goto-cancel").addEventListener("click", hidePlan);
$("goto-run").addEventListener("click", async () => {
  if (!gotoPlanId) return;
  const id = gotoPlanId;
  hidePlan();
  try {
    const r = await (await postJson("/api/goto", {plan_id: id})).json();
    if (r.error) showPlanError(r.error);
    else activate(null);
  } catch (e) { showPlanError("サーバーに接続できません"); }
});
$("track-start").addEventListener("click", async () => {
  if (!trackTarget) return;
  const body = await (await postJson("/api/tracking", {target: trackTarget, guide: $("track-guide").checked})).json();
  if (body.error) showPlanError(body.error);
  else activate(null);
});
$("track-synscan").addEventListener("click", async () => {
  const body = await (await postJson("/api/tracking", {mode: "synscan", target: trackTarget})).json();
  if (body.error) showPlanError(body.error);
  else activate(null);
});
$("stop-track").addEventListener("click", async () => {
  await fetch("/api/tracking", {method: "DELETE"});
  activate(null);
});
$("open-capture").addEventListener("click", () => { $("capture").hidden = false; activate($("capture")); refreshCaptures(); });
$("close-capture").addEventListener("click", () => activate(null));
$("shoot-still").addEventListener("click", () => shoot("/api/capture/still", {}));
$("shoot-timelapse").addEventListener("click", () => shootManual("/api/capture/timelapse", {interval: +$("timelapse-interval").value}));
$("shoot-video").addEventListener("click", () => shootManual("/api/capture/video", {seconds: +$("video-seconds").value}));
$("shoot-stop").addEventListener("click", () => shoot("/api/capture/stop", {}));

// 対応するブラウザでは全画面にして横向きに固定する
$("fullscreen").addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) { await document.exitFullscreen(); return; }
    await document.documentElement.requestFullscreen();
    await screen.orientation.lock("landscape");
  } catch (e) { /* 非対応のブラウザでは CSS の回転で横表示を保つ */ }
});

render();
connectStatus();

// 観測地の地図。地理院タイルを表示し、画面中央の ＋ に望遠鏡の位置を合わせる
const GSI_ATTRIBUTION = '出典：<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank">国土地理院（地理院タイル）</a>';
const MAP_NOTE = "写真では高い建物の上の方が外側へ倒れて写ります。建物の位置は標準地図の輪郭で確かめてください。";
let siteMap = null, mapLayers = null, mapLayer = "photo", mapMarks = null, mapOrigin = null;
function mapOffset(center) {
  if (!mapOrigin) return "";
  const r = 6371000, rad = Math.PI / 180;
  const north = (center.lat - mapOrigin.lat) * rad * r;
  const east = (center.lng - mapOrigin.lng) * rad * r * Math.cos(center.lat * rad);
  return `　${mapOrigin.label}から ${north >= 0 ? "北" : "南"} ${Math.abs(north).toFixed(1)} m、${east >= 0 ? "東" : "西"} ${Math.abs(east).toFixed(1)} m`;
}
function showMapCenter() {
  const c = siteMap.getCenter();
  $("map-center").textContent = `＋ の位置 ${c.lat.toFixed(6)}° ${c.lng.toFixed(6)}°` + mapOffset(c);
}
function createMap() {
  siteMap = L.map("map", {maxZoom: 21, zoomSnap: 0.25, zoomDelta: 0.5});
  siteMap.attributionControl.setPrefix('<a href="https://leafletjs.com/" target="_blank">Leaflet</a>');
  const layer = (name, ext) => L.tileLayer(`https://cyberjapandata.gsi.go.jp/xyz/${name}/{z}/{x}/{y}.${ext}`,
    {maxNativeZoom: 18, maxZoom: 21, attribution: GSI_ATTRIBUTION});
  mapLayers = {photo: layer("seamlessphoto", "jpg"), std: layer("std", "png")};
  for (const l of Object.values(mapLayers)) {
    l.on("tileerror", () => { $("map-note").textContent = "地図を読み込めません（インターネットに接続していない可能性があります）。測位か手入力で設定してください"; });
  }
  mapLayers[mapLayer].addTo(siteMap);
  mapMarks = L.layerGroup().addTo(siteMap);
  siteMap.on("move", showMapCenter);
}
function setMapLayer(name) {
  siteMap.removeLayer(mapLayers[mapLayer]);
  mapLayer = name;
  mapLayers[name].addTo(siteMap);
  $("map-layer").textContent = name === "photo" ? "標準地図にする" : "写真にする";
}
function closeMap() {
  $("align").hidden = false;
  activate($("align"));
}
$("site-map-open").addEventListener("click", () => {
  if (typeof L === "undefined") { $("site-state").textContent = "地図の部品を読み込めませんでした"; return; }
  stopMeasure();
  const lat = fieldNumber("site-lat"), lon = fieldNumber("site-lon");
  if (lat === null || lon === null) { $("site-state").textContent = "先に位置を測るか、緯度と経度を入力してください"; return; }
  $("site-map").hidden = false;
  activate($("site-map"));
  if (!siteMap) createMap();
  $("map-note").textContent = MAP_NOTE;
  mapMarks.clearLayers();
  if (siteMeasured) {
    mapOrigin = {lat: siteMeasured.latitude, lng: siteMeasured.longitude, label: "測位"};
    L.circle(mapOrigin, {radius: siteMeasured.accuracy, color: "#1e7be0", weight: 1, fillOpacity: 0.1, interactive: false}).addTo(mapMarks);
  } else {
    mapOrigin = {lat, lng: lon, label: "入力値"};
  }
  L.circleMarker(mapOrigin, {radius: 5, color: "#fff", weight: 2, fillColor: "#1e7be0", fillOpacity: 1, interactive: false}).addTo(mapMarks);
  $("map-home").textContent = `${mapOrigin.label}の位置へ`;
  // 非表示の間は大きさが 0 なので、表示してから大きさを測り直す
  siteMap.invalidateSize();
  siteMap.setView([lat, lon], 19);
  showMapCenter();
});
$("map-layer").addEventListener("click", () => setMapLayer(mapLayer === "photo" ? "std" : "photo"));
$("map-home").addEventListener("click", () => siteMap.setView(mapOrigin, siteMap.getZoom()));
$("map-cancel").addEventListener("click", closeMap);
$("map-adopt").addEventListener("click", async () => {
  const c = siteMap.getCenter();
  siteAdopted = {latitude: c.lat, longitude: c.lng};
  $("site-lat").value = c.lat.toFixed(6);
  $("site-lon").value = c.lng.toFixed(6);
  closeMap();
  $("site-state").textContent = "地面の標高とジオイド高を地理院から取得しています…";
  try {
    const r = await (await fetch(`/api/site/lookup?lat=${c.lat.toFixed(6)}&lon=${c.lng.toFixed(6)}`)).json();
    if (r.ground_m !== null) $("site-ground").value = r.ground_m;
    if (r.geoid_m !== null) $("site-geoid").value = r.geoid_m;
    updateElevation();
    const missing = [r.ground_m === null && "地面の標高", r.geoid_m === null && "ジオイド高"].filter(Boolean);
    $("site-state").textContent = (missing.length ? `${missing.join("と")}を取得できませんでした。手で入力してください。` :
      `地面 ${r.ground_m} m（${r.ground_source}）、ジオイド高 ${r.geoid_m} m。`) +
      (fieldNumber("site-height") === null ? "地面から望遠鏡までの高さを入れて保存してください" : "確かめて保存してください");
  } catch (e) { $("site-state").textContent = "地理院の値を取得できませんでした。手で入力してください"; }
});
