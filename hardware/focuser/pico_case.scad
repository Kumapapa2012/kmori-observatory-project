// フォーカス電動化: Pico H (ヘッダー付き、マイクロ USB) のケース。第 4 版・仮値。2026-11-24
//
// 方針 (ユーザー 2026-11-24): ワイヤー・本体・ワイヤーのインライン型。Pico はサーボの線の途中に置き、USB ケーブルでぶら下がる。
//   中継基板は作らず、Pico のヘッダーピンにジャンパー線 (メス、1 本ずつ) を直接差す。コンデンサ (470µF 前後) は線の途中に入れる。
// 第 2 版の変更 (ユーザー指示):
//   * サーボ側の線は、結束バンドでなく、ケースの中で S 字に折って格納し、ふたで押さえ込む。線の出口側に、迷路 (ふたの翼 + 底の仕切り板 3 枚) を付けた。
//   * USB 側のケーブルは、プラグがある程度ロックされるので、コネクタを外に出すだけ。受け台と結束バンドの穴は廃止。
//   * 全体に丸みを付けた (外形の角 R4、ふたの上の縁 R2、底の縁 R1、内側の角 R1.5)。
//   * 全高を約 25 に (ピンヘッダ込みの Pico 12.5 + メスのジャンパーの分)。
// 第 3 版 (ユーザー 2026-11-24: 3 ピンヘッダ (オス) が手元にある。サーボの接続にこれを使う): ヘッダーをケース内、迷路の先に置く。
//   サーボの線は、迷路で S 字に折ってふたで押さえ、本体の出口側の壁の切り欠きから廊下へ入り、端のメスのコネクタをヘッダーの長い足 (6) に差す。
//   ヘッダーの本体 (2.5) は、床の上の凹み (側壁 + 櫛状の歯) に入れ、抜く向きの力を歯で受ける。短い足 (3) は反対側 (Pico 側) へ出るので、
//   Pico のジャンパー 3 本をここにはんだ付けする。コンデンサは、2 本のリブの間の高い空間 (板の下の中央) に立てて、ヘッダーの 5V と GND の足につなぐ。
//   コネクタを横に寝かせて差すので、廊下を 2 → 3 に高くし、さらにジャンパーの線を曲げる余裕 (メスの筒 14 は実測、ユーザー) のため 4.5 にした (全高 約 28)。
// 第 4 版 (ユーザー 2026-11-24: サーボのケーブルは平べったいので、ケースとふたで上下から波打つように押さえる): 迷路を、左右の仕切り板 (面内の S 字)
//   から、上下の山 (半円柱、軸は y) に変えた。底の山 3 つの上を線が越え、ふたの山 2 つの下をくぐる (x-z 面の波)。両側に低い壁 (幅 6 の溝)
//   で、平たい線が横にずれないようにした (線は 幅 3.5 × 厚み 1.1 で、溝は幅 4.5)。波の高さは、線の厚み 1.1 に対して 山と山の高低差 約 1.4。
//
// 単位 mm。座標: 内側の USB 側の端 = x 0、+x = 反対側 (線の出口)、y = 幅方向 (中心 0)、z = ケースの底の外面から上。
// 構成 (上下は水平分割。分割面 z = 3.5 は、線を通す「廊下」の天井):
//   BASE (底、下の浅い皿 z=0〜3.5) = 底 + 外壁 + 線の迷路の仕切り板 + Pico を下から支える細いリブ 2 本。
//   LID  (ふた、上の背の高い箱 + 出口側の薄い翼) = 天井 + 外壁 + Pico を上から押さえる突起 + USB のプラグの切り欠き + 翼の押さえリブ。
//   Pico は、ふたを逆さにして USB 側からはめ、ジャンパーを差してから、線を迷路に通して BASE をかぶせ、底から M2 のタッピングビス 6 本で留める。
//   Pico は部品面を上、ヘッダーの長いピン (下向き) を下にして置く。板の縁の外側にヘッダー本体があるので、板の縁では支えず、
//   ヘッダーの内側の細いリブ 2 本 (BASE) で下から支え、天井の突起 4 つで上から軽く押さえる。
//   ジャンパーのメスの筒の下端 (z=3.5) から、線は廊下 (高さ 2) を通って、出口側の壁の切り欠きから迷路へ。
// 部品: part = "BASE" | "LID" | "CHECK" (板・ジャンパーとの干渉) | "CHECK_PLUG" (プラグとの干渉) | "all"
// 未確認 (すべて仮値): Pico H の実寸 (板 51 × 21、ヘッダー本体 2.5 + 長いピン 6、USB シェルの出っ張り 約 1.3)、ジャンパーのメスの筒の長さ (14 と仮定)、
//   マイクロ USB プラグの外形 (幅 11、高さ 8 と仮定)、天井の突起と部品 (BOOTSEL、チップ) の干渉、線の太さ (外径 1.3 と仮定) と迷路の寸法、ねじ (M2 タッピング)。
//   実物の Pico とプラグ、ジャンパーで確認が必要。

$fn = 48;
part = "all";

// ---- Pico H (仮) ----
pico_L = 51.0;  pico_W = 21.0;  pico_t = 1.0;
usb_over = 1.3;                    // USB のシェルが板の端から出る長さ
row_y = 17.78 / 2;                 // ピンの列の中心 (±8.89)
hdr_h = 2.5;                       // ヘッダー本体の厚み (板の下面から)
jump_len = 14;                     // ジャンパーのメスの筒の長さ (仮)

// ---- ケース (仮) ----
wall_s = 3.5;                      // 長辺の壁 (ねじを受ける)
wall_e = 2.5;                      // 短辺の壁
floor_t = 1.5;
gallery = 4.5;                     // 線の廊下の高さ (床の上面から分割面まで)
z_split = floor_t + gallery;       // 分割面 3.5
side_clr = 0.3;
Wi = pico_W + 2 * side_clr;        // 内側の幅
x_board0 = usb_over + 0.3;
Li = x_board0 + pico_L + 0.6;      // 内側の長さ
z_pcb_bot = z_split + hdr_h + jump_len;   // 板の下面 (ジャンパーの下端が分割面)
z_pcb_top = z_pcb_bot + pico_t;
above = 3.0;                       // 板の上面から天井の下面まで (USB シェルの高さ 2.7 + 余裕)
ceil_t = 1.5;
z_ceil = z_pcb_top + above;        // 天井の下面
z_top = z_ceil + ceil_t;           // 全高
R_out = 4;  R_in = 1.5;  R_top = 2;  R_bot = 1;

rib_y = 5.4;  rib_w = 1.6;         // 板を下から支えるリブ
arm_notch = [[4.5, 10.0], [22.5, 29.0], [42.0, 47.0]];   // リブの切り欠きの x の範囲 (板の USB 側の端から)。Pico H の腕 (写真から目測: 5.7〜8.9、23.6〜27.9、43.2〜45.9) に両側 約 1 の余裕。要実測
pad_x = [18, 46];  pad_y = 5.4;  pad_s = 3;
screw_x = [12, 47];                // 本体のねじ (2 組目はケーブル抑えの側へ寄せた。ユーザー 2026-11-24)
screw_y = Wi / 2 + wall_s / 2;
pilot_d = 1.7;  pilot_h = 8;  clear_d = 2.4;  cb_d = 4.2;  cb_h = 0.8;

// USB 側 (プラグは外に出すだけ)
plug_w = 11;  plug_h = 8;          // プラグの外形 (仮)
usb_notch_w = 14;
usb_z0 = z_pcb_top + 1.35 - plug_h / 2 - 0.5;   // 切り欠きの下端 (シェルの中心 = 板の上面 + 1.35)

// 線の出口側 (迷路)
exit_w = 10;                       // 本体の壁の切り欠き
wing_len = 28;  wing_w = 16;  wing_wall = 2;
wing_x0 = Li + wall_e;             // 翼の始まり
cable_w = 3.5;  cable_t = 1.1;      // サーボのケーブル (平たい。ユーザー実測 2026-11-24)
channel_hw = (cable_w + 1.0) / 2;  rail_t = 1.2;   // 線の溝の半幅 (幅 4.5 = 線の幅 + 1.0) と、両側の壁の厚み
ridge_r = 1.8;                     // 山の半径 (半円柱、軸は y)
ridge_xb = [4, 12, 20];            // 底の山の位置 (翼の始まりから)
ridge_xl = [8, 16];                // ふたの山の位置
ridge_zl = floor_t + ridge_r - 0.3;   // ふたの山の下端 (底の山の頂上より 0.3 低い → 線は 約 1.5 波打つ)
wing_inner_hw = wing_w / 2 - wing_wall;     // 6
wing_exit_w = 6;
wscrew_x = wing_len - 5;  wscrew_y = 5.4;

// ---- 3 ピンヘッダ (オス、手元のもの) ----
hdr3_body = 2.5;                   // 本体の厚み (ピンの向き)
hdr3_hw = 3.95;                    // 凹みの内側の半幅 (本体の幅 7.62 + 0.3)
hdr3_x = Li - 13;                  // 本体の Pico 側の面の位置
comb_t = 0.8;  slot_w = 1.0;       // 櫛の歯の厚みと、ピンを通す溝の幅
conn_len = 9.5;  conn_hw = 4.05;  conn_h = 2.6;   // サーボのメスのコネクタ (仮)

// ---- 外形 (2 次元) ----
module rrect(x0, x1, y0, y1, r) {
    translate([x0 + r, y0 + r]) offset(r = r) square([x1 - x0 - 2 * r, y1 - y0 - 2 * r]);
}
module main2d() { rrect(-wall_e, Li + wall_e, -(Wi / 2 + wall_s), Wi / 2 + wall_s, R_out); }
module wing2d() { rrect(wing_x0 - 6, wing_x0 + wing_len, -wing_w / 2, wing_w / 2, 3); }
module outline2d() {
    offset(r = -1.5) offset(delta = 1.5) union() { main2d(); wing2d(); }     // 内側の角 (凹) を丸める
}
module cavity2d() { rrect(0, Li, -Wi / 2, Wi / 2, R_in); }
module wing_cavity2d() {
    rrect(wing_x0 - 0.01, wing_x0 + wing_len - wing_wall, -wing_inner_hw, wing_inner_hw, 1.5);
}

// 縁の丸め (段付きの近似、層厚 約 0.25)
function rr(r, k, n) = r - sqrt(r * r - pow(r - (k + 0.5) * r / n, 2));   // k 番目の層の内寄せ量 (k=0 が縁の端)
module ext_round(z0, z1, rb, rt) {
    nb = max(1, round(rb * 4));  nt = max(1, round(rt * 4));
    // 本体
    translate([0, 0, z0 + rb]) linear_extrude(height = z1 - z0 - rb - rt + 0.001) children();
    // 底の縁
    if (rb > 0) for (k = [0 : nb - 1])
        translate([0, 0, z0 + k * rb / nb]) linear_extrude(height = rb / nb + 0.001)
            offset(delta = -rr(rb, k, nb)) children();
    // 上の縁
    if (rt > 0) for (k = [0 : nt - 1])
        translate([0, 0, z1 - rt + (nt - 1 - k) * rt / nt]) linear_extrude(height = rt / nt + 0.001)
            offset(delta = -rr(rt, k, nt)) children();
}

// ---- BASE ----
module base() {
    difference() {
        union() {
            ext_round(0, z_split, R_bot, 0) outline2d();
        }
        // 内側 (床の上面まで)
        translate([0, 0, floor_t]) linear_extrude(height = z_split) cavity2d();
        translate([0, 0, floor_t]) linear_extrude(height = z_split) wing_cavity2d();
        // 本体の出口側の壁の切り欠き
        translate([Li - 0.1, -exit_w / 2, floor_t]) cube([wall_e + 0.2, exit_w, z_split]);
        // 翼の端の出口
        translate([wing_x0 + wing_len - wing_wall - 0.1, -wing_exit_w / 2, floor_t]) cube([wing_wall + 0.2, wing_exit_w, z_split]);
    }
    // 線の波: 底の山 (半円柱、軸は y) と、両側の壁
    for (x = ridge_xb)
        intersection() {
            translate([wing_x0 + x, -channel_hw, floor_t]) rotate([-90, 0, 0]) cylinder(r = ridge_r, h = 2 * channel_hw, $fn = 40);
            translate([0, -50, floor_t - 0.01]) cube([200, 100, gallery]);
        }
    for (s = [-1, 1])
        translate([wing_x0, s > 0 ? channel_hw : -channel_hw - rail_t, floor_t - 0.01])
            cube([wscrew_x - 3, rail_t, gallery + 0.01]);
    // 翼のねじの台
    for (s = [-1, 1])
        translate([wing_x0 + wscrew_x, s * wscrew_y, floor_t - 0.01]) cylinder(d = 5.0, h = gallery + 0.01);
    // Pico を下から支えるリブ
    // 板の下のヘッダーの腕 (黒い樹脂の横桟、厚み hdr_h) を逃げる切り欠き付き (ユーザーが印刷後に手で切った。2026-11-25)
    for (s = [-1, 1]) difference() {
        translate([x_board0 + 2, s * rib_y - rib_w / 2, floor_t - 0.01])
            cube([pico_L - 4, rib_w, z_pcb_bot - floor_t + 0.01]);
        for (n = arm_notch)
            translate([x_board0 + n[0], s * rib_y - rib_w, z_pcb_bot - hdr_h - 0.3])
                cube([n[1] - n[0], 2 * rib_w, hdr_h + 0.4]);
    }
    header_pocket();
}
// ヘッダーの凹み: 側壁 2 枚 + 櫛の歯 (ピンの溝つき)
module header_pocket() {
    x0 = hdr3_x - 1.0;  x1 = hdr3_x + hdr3_body + comb_t;
    for (s = [-1, 1])
        translate([x0, s > 0 ? hdr3_hw : -hdr3_hw - 1.2, floor_t - 0.01]) cube([x1 - x0, 1.2, gallery + 0.01]);
    // 歯 (ピンは y = -2.54, 0, 2.54。溝は幅 slot_w)
    for (r = [[-hdr3_hw, -2.54 - slot_w / 2], [-2.54 + slot_w / 2, -slot_w / 2], [slot_w / 2, 2.54 - slot_w / 2], [2.54 + slot_w / 2, hdr3_hw]])
        translate([hdr3_x + hdr3_body, r[0], floor_t - 0.01]) cube([comb_t, r[1] - r[0], gallery + 0.01]);
    // 溝の下の床 (ピンの下に 0.7)
    translate([hdr3_x + hdr3_body, -hdr3_hw, floor_t - 0.01]) cube([comb_t, 2 * hdr3_hw, 0.7 + 0.01]);
}

module base_final() {
    difference() {
        base();
        // ねじの穴 (底から。皿の座ぐり付き)
        for (x = screw_x, s = [-1, 1], y = [s * screw_y]) {
            translate([x, y, -1]) cylinder(d = clear_d, h = z_split + 2, $fn = 24);
            translate([x, y, -0.01]) cylinder(d = cb_d, h = cb_h + 0.01, $fn = 24);
        }
        for (s = [-1, 1]) {
            translate([wing_x0 + wscrew_x, s * wscrew_y, -1]) cylinder(d = clear_d, h = z_split + 2, $fn = 24);
            translate([wing_x0 + wscrew_x, s * wscrew_y, -0.01]) cylinder(d = cb_d, h = cb_h + 0.01, $fn = 24);
        }
    }
}

// ---- LID ----
module lid() {
    difference() {
        union() {
            // 背の高い箱 (本体の外形、分割面から全高まで、上の縁を丸める)
            ext_round(z_split, z_top, 0, R_top) main2d();
            // 出口側の薄い翼
            translate([0, 0, z_split]) linear_extrude(height = 1.5)
                difference() { wing2d(); main2d(); }
            // 翼のねじの台 (上へ)
            for (s = [-1, 1])
                translate([wing_x0 + wscrew_x, s * wscrew_y, z_split]) cylinder(d = 5.2, h = 6.5);
            // 板を押さえる突起
            for (x = pad_x, s = [-1, 1])
                translate([x_board0 + x - pad_s / 2, s * pad_y - pad_s / 2, z_pcb_top + 0.1])
                    cube([pad_s, pad_s, z_ceil - z_pcb_top - 0.1 + 0.01]);
            // ふたの山 (半円柱、軸は y。翼の板から下へ)
            for (x = ridge_xl)
                translate([wing_x0 + x, -channel_hw, ridge_zl + ridge_r]) rotate([-90, 0, 0]) cylinder(r = ridge_r, h = 2 * channel_hw, $fn = 40);
        }
        // 内側 (突起は上で足したので、ここで先に抜くと突起も消える。順序のため後で足す)
        translate([0, 0, z_split - 0.01]) linear_extrude(height = z_ceil - z_split + 0.01) cavity2d();
        // USB のプラグの切り欠き (上まで抜ける)
        translate([-wall_e - 0.1, -usb_notch_w / 2, usb_z0]) cube([wall_e + 0.9, usb_notch_w, z_top]);   // 壁と、プラグの根元 (x<0.8) の天井も抜く
        // ねじの下穴
        for (x = screw_x, s = [-1, 1])
            translate([x, s * screw_y, z_split - 0.01]) cylinder(d = pilot_d, h = pilot_h, $fn = 24);
        for (s = [-1, 1])
            translate([wing_x0 + wscrew_x, s * wscrew_y, z_split - 0.01]) cylinder(d = pilot_d, h = 5.5, $fn = 24);
    }
    // 板を押さえる突起 (内側を抜いた後に足す)
    for (x = pad_x, s = [-1, 1])
        translate([x_board0 + x - pad_s / 2, s * pad_y - pad_s / 2, z_pcb_top + 0.1])
            cube([pad_s, pad_s, z_ceil - z_pcb_top - 0.1 + 0.01]);
}

// ---- 参照物 (確認用) ----
module pico_ref() {
    translate([x_board0, -pico_W / 2, z_pcb_bot]) cube([pico_L, pico_W, pico_t]);
    translate([x_board0 - usb_over, -4, z_pcb_top]) cube([usb_over + 6, 8, 2.7]);   // USB シェル
}
module jumper_ref() {   // 18 番 (GND)・20 番 (GP15) は y=+8.89 の列、40 番 (VBUS) は反対の列 (仮の並び)
    for (p = [[18, 1], [20, 1], [40, -1]])
        translate([x_board0 + 1.6 + ((p[0] > 20 ? 40 - p[0] : p[0] - 1)) * 2.54 - 1.27, p[1] * row_y - 1.27, z_split])
            cube([2.54, 2.54, jump_len]);
}
module conn3_ref() {   // サーボのメスのコネクタ (ヘッダーに差した状態)
    translate([hdr3_x + hdr3_body + comb_t, -conn_hw, floor_t]) cube([conn_len, 2 * conn_hw, conn_h]);
    translate([hdr3_x, -3.81, floor_t]) cube([hdr3_body, 7.62, 2.5]);   // ヘッダー本体
}
module plug_ref() {   // マイクロ USB のプラグの外形 (仮)。シェルの前端まで入った状態
    translate([-30, -plug_w / 2, z_pcb_top + 1.35 - plug_h / 2]) cube([30 + 0.3, plug_w, plug_h]);
}

if (part == "NONE") { }
else if (part == "BASE") base_final();
else if (part == "LID") lid();
else if (part == "CHECK") { intersection() { union() { base_final(); lid(); } union() { pico_ref(); jumper_ref(); } } }
else if (part == "CHECK_HDR") { intersection() { union() { base_final(); lid(); } conn3_ref(); } }
else if (part == "CHECK_PLUG") { intersection() { union() { base_final(); lid(); } plug_ref(); } }
else { base_final(); color("white", 0.5) lid(); color("green", 0.6) pico_ref(); color("red", 0.6) jumper_ref(); }
