// ========================================================
// ファインダーカメラホルダー v3  (ELP USBFHD06H-FD100 + M12 12mm)
// 単位 mm。材質 PETG。
// 組立座標: z=0 がレンズ側の外面、+z がファインダー側。-y が「下」(ケーブル出口の側)。
// ========================================================

/* [表示] */
PART = "all"; // ["all":印刷配置, "front", "back", "test_collar":筒だけの試し刷り, "assembly", "section"]

/* [ファインダー装着部: 接眼側の筒の実測 2026-11-28] */
eye_d_tip = 27.75;     // 先端の直径
eye_d_step = 28.25;    // 段の手前の直径 (先端より太いテーパー)
eye_len = 21;            // 先端から段まで
fit_adj = 0;           // 内径の調整 (直径)。きつい→+0.2、ゆるい→-0.2

/* [カメラ基板] */
pcb = 38.0;  pcb_t = 1.6;  pitch = 28.0;
boss_h = 3.0;          // 前板の内面から基板表面まで
back_gap = 12.0;       // 基板裏面から奥まで (線の盛り上がりの余裕込み)
holder_sq = 16.8;      // レンズマウント角穴 (16 + 0.8)
ear_len = 24.8;  ear_w = 4.8;   // マウントの耳の逃げ
screw_w = 6.0;                  // レンズ止めねじ突起の逃げ: 幅 (頭 約3)
screw_d = 3.0;                  // 同: 角穴の上辺 (+y) からの深さ

/* [ケース] */
in_x = 21.8;  in_y = 19.8;      // 内側の半幅
wall = 2.0;   front_t = 2.0;  back_t = 2.5;  corner_r = 3.0;

/* [はめ込み: 爪は使わない] */
// 前板の低い側板 (±x) の突条が、背面の壁の内側の溝にはまる。
sk_t = 1.6;     // 側板の厚み
sk_h = 5.5;     // 側板の高さ
sk_len = 28;    // 側板の長さ
sk_gap = 0.2;   // 側板と背面の壁の隙間
bump = 0.25;    // 締め代 (壁を押し広げる量)。固い→下げる、ゆるい→上げる
bump_len = 12;
bump_z = 5.5;   // 突条の頂の高さ

/* [ケーブル出口] */
// コネクタ端 → 4本線 約15 → 細い被覆 10 → 太さ 5 の部分。
// 細い被覆を前板の舌と背面で挟む。太い部分は外に残り、抜け止めになる。
sleeve_d = 4.0;        // 細い被覆の径 (実物 約4)
sleeve_play = 0.2;     // 穴を径より大きくする量 (印刷で穴は小さくなる)
cab_x = 9;             // コネクタから横に離し、4本線の長さを内側で使う
cab_z = 12.8;          // 穴の中心の高さ
tongue_w0 = 11;        // 出口の溝の幅: 前板側 (根元)
tongue_w1 = 7;         //               穴の中心の高さ (先端)
tongue_gap = 0.25;     // 舌と溝の隙間 (片側)
edge_c = 0.5;          // 背面の開口の面取り (1層目のはみ出し逃げ)

/* [ファインダー筒] */
col_len = 21;  col_wall = 3.0;  col_fillet = 4.5;
n_slit = 3;  slit_w = 2.0;  slit_len = 16;

$fn = 96;
e = 0.01;

out_x = in_x + wall;  out_y = in_y + wall;
z_pcb = front_t + boss_h;                 // 基板表面
z_in  = z_pcb + pcb_t + back_gap;         // 奥の内面
z_out = z_in + back_t;                    // 背面の外面
sk_xo = in_x - sk_gap;                    // 側板の外面
col_od = eye_d_step + fit_adj + 2*col_wall;

module rrect(hx, hy, h, r) linear_extrude(h) offset(r=r) square([2*(hx-r), 2*(hy-r)], center=true);

module cable_hole()
    translate([cab_x, -out_y - 1, cab_z]) rotate([-90, 0, 0])
        cylinder(d=sleeve_d + sleeve_play, h=wall + 2);

// ---------------- 前板 (レンズ側) ----------------
// XZ 断面を Y 方向に長さ len で押し出す
module xz(len) translate([0, len/2, 0]) rotate([90, 0, 0]) linear_extrude(len) children();

module skirt() {   // +x 側
    z1 = front_t + sk_h;
    xz(sk_len) polygon([
        [sk_xo - sk_t - 0.8, front_t - e], [sk_xo, front_t - e],
        [sk_xo, z1 - 0.6], [sk_xo - 0.6, z1],               // 先端の外側の面取り
        [sk_xo - sk_t, z1], [sk_xo - sk_t, front_t + 0.8]
    ]);
    xz(bump_len) polygon([
        [sk_xo - e, bump_z - 0.6], [sk_xo + sk_gap + bump, bump_z - 0.1],   // 抜け側 約40°
        [sk_xo + sk_gap + bump, bump_z + 0.2], [sk_xo - e, bump_z + 1.4]    // 入り側はゆるい斜面
    ]);
}

// 出口の舌と溝の台形 (XZ 断面)。gap だけ細くする
module wedge(z0, gap, ext=0) {   // ext: 切り抜くとき壁の内外にはみ出す量
    k = (tongue_w0 - tongue_w1) / 2 / (cab_z - front_t);   // 片側の傾き
    h0 = tongue_w0/2 - gap + k*(front_t - z0);
    h1 = tongue_w1/2 - gap;
    translate([cab_x, -out_y, 0]) rotate([90, 0, 0]) translate([0, 0, -wall - ext])
        linear_extrude(wall + 2*ext) polygon([[-h0, z0], [h0, z0], [h1, cab_z], [-h1, cab_z]]);
}

module front() {
    difference() {
        union() {
            rrect(out_x, out_y, front_t, corner_r);
            for (m = [0, 1]) mirror([m, 0, 0]) skirt();
            // 基板ボス
            for (x = [-1, 1], y = [-1, 1])
                translate([x*pitch/2, y*pitch/2, front_t - e]) cylinder(d=5, h=boss_h + e);
            // 位置決めリブ (上側 全幅、下側は舌の左右)
            translate([-14, in_y - 0.2 - 0.9, front_t - e]) cube([28, 0.9, 1.8]);
            translate([-14, -in_y + 0.2, front_t - e]) cube([14 + cab_x - tongue_w0/2, 0.9, 1.8]);
            translate([cab_x + tongue_w0/2, -in_y + 0.2, front_t - e]) cube([17 - cab_x - tongue_w0/2, 0.9, 1.8]);
            // ケーブル出口の舌 (くさび形。先端の半円で被覆を押さえる)
            difference() {
                wedge(front_t - e, tongue_gap);
                cable_hole();
            }
        }
        // レンズマウントと耳の穴
        translate([-holder_sq/2, -holder_sq/2, -1]) cube([holder_sq, holder_sq, front_t + 2]);
        translate([-ear_len/2, -ear_w/2, -1]) cube([ear_len, ear_w, front_t + 2]);
        // レンズ止めねじ (上側 = ケーブルと反対側)
        translate([-screw_w/2, holder_sq/2 - e, -1]) cube([screw_w, screw_d + e, front_t + 2]);
        // M2 タッピング下穴 (深さ 4.2、M2x5 用。前面には抜けない)
        for (x = [-1, 1], y = [-1, 1])
            translate([x*pitch/2, y*pitch/2, z_pcb - 4.2]) cylinder(d=1.7, h=4.3);
    }
}

// ---------------- 背面シェル + ファインダー筒 ----------------
module collar() {
    r_i = (eye_d_tip + fit_adj)/2;          // 奥 (先端が当たる側)
    r_m = (eye_d_step + fit_adj)/2;         // 入口 (段の手前が当たる側)
    r_o = col_od/2;  L = col_len;  z0 = z_out;
    difference() {
        rotate_extrude() polygon(concat(
            [[r_i, z0 - e], [r_o + col_fillet, z0 - e]],
            // 根元の凹フィレット
            [for (a = [270:-5:180]) [r_o + col_fillet + col_fillet*cos(a),
                                     z0 + col_fillet + col_fillet*sin(a)]],
            [[r_o, z0 + L - 3], [r_o + 0.6, z0 + L - 2], [r_o + 0.6, z0 + L - 0.6],
             [r_o, z0 + L], [r_m + 0.8, z0 + L],              // 入口の面取り
             [r_m, z0 + L - 0.8],
             // 内側のテーパー: 入口から eye_len の深さで先端の径になる
             [r_i, z0 + L - eye_len]]
        ));
        // スリット (端は丸)。下側を避けて配置
        for (i = [0:n_slit-1]) rotate([0, 0, 90 + i*360/n_slit]) hull() {
            for (z = [z0 + L - slit_len + slit_w/2, z0 + L + 2])
                translate([0, 0, z]) rotate([0, 90, 0]) cylinder(d=slit_w, h=col_od);
        }
    }
}

module back() {
    difference() {
        union() {
            translate([0, 0, front_t]) rrect(out_x, out_y, z_out - front_t, corner_r);
            collar();
        }
        translate([0, 0, front_t - 1]) rrect(in_x, in_y, z_in - front_t + 1, 1.0);
        // 開口の内側の面取り
        hull() {
            translate([0, 0, front_t - e]) rrect(in_x + edge_c, in_y + edge_c, e, 1.0);
            translate([0, 0, front_t + edge_c]) rrect(in_x, in_y, e, 1.0);
        }
        // 背面の抜き穴 (筒の底は接眼部の突き当て)
        translate([0, 0, z_in - 1]) cylinder(d=20, h=back_t + 2);
        // 突条がはまる溝
        for (m = [0, 1]) mirror([m, 0, 0]) xz(bump_len + 1) polygon([
            [in_x - e, bump_z - 0.45], [in_x + bump + 0.1, bump_z - 0.15],
            [in_x + bump + 0.1, bump_z + 0.6], [in_x - e, bump_z + 1.1]
        ]);
        // ケーブル出口: 開口側が広い台形の溝、その奥に半円
        wedge(front_t - 1, 0, 1);
        cable_hole();
        // こじ開け溝
        for (s = [-1, 1])
            translate([s*out_x - 1.2, 7, front_t - e]) cube([2.4, 6, 1.2]);
    }
}

// ---------------- 筒だけの試し刷り ----------------
module test_collar() {
    translate([0, 0, 2 - z_out]) collar();
    difference() {
        cylinder(r=col_od/2 + col_fillet, h=2);
        translate([0, 0, -1]) cylinder(d=20, h=4);
    }
}

module pcb_mock() {
    translate([-pcb/2, -pcb/2, z_pcb]) cube([pcb, pcb, pcb_t]);
    translate([-8, -8, z_pcb - 14.5]) cube([16, 16, 14.5]);
    translate([-12, -2, z_pcb - 4]) cube([24, 4, 4]);
    translate([0, 0, z_pcb - 24]) cylinder(d=14, h=10);
    translate([-10, -15.6, z_pcb + pcb_t]) cube([10, 5.2, 9]);   // 4 ピン + プラグ
    // 細い被覆 10 と太い部分
    translate([cab_x, -out_y, cab_z]) rotate([-90, 0, 0]) cylinder(d=sleeve_d, h=10);
    translate([cab_x, -out_y, cab_z]) rotate([90, 0, 0]) cylinder(d=5, h=10);
}

if (PART == "front") front();
else if (PART == "back") translate([0, 0, -front_t]) back();
else if (PART == "test_collar") test_collar();
else if (PART == "assembly") { color("gold") front(); color("orange", 0.5) back(); color("green") pcb_mock(); }
else if (PART == "section") difference() {
    union() { color("gold") front(); color("orange") back(); color("green") pcb_mock(); }
    translate([0, -60, -30]) cube([60, 120, 100]);
}
else {  // 印刷配置: 前板は外面を下、背面は開口を下 (内側にサポート要)
    front();
    translate([2*out_x + 8, 0, -front_t]) back();
}
