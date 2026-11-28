// ========================================================
// ファインダーカメラホルダー v2  (ELP USBFHD06H-FD100 + M12 12mm)
// 単位 mm。材質 PETG。
// 組立座標: z=0 がレンズ側の外面、+z がファインダー側。-y が「下」(ケーブル出口の側)。
// ========================================================

/* [表示] */
PART = "all"; // ["all":印刷配置, "front", "back", "test_rings":はめあい確認リング, "assembly", "section"]

/* [ファインダー装着部: 確認リングで決める] */
finder_fit = 27.25;    // 筒の内径 (確認リングで「軽く固い」径)
pad_interf = 0.25;     // 爪の先端の締め代 (半径)

/* [カメラ基板] */
pcb = 38.0;  pcb_t = 1.6;  pitch = 28.0;
boss_h = 3.0;          // 前板の内面から基板表面まで
back_gap = 10.5;       // 基板裏面から奥まで (実測 9 以下 + 余裕)
holder_sq = 16.8;      // レンズマウント角穴 (16 + 0.8)
ear_len = 24.8;  ear_w = 4.8;   // マウントの耳の逃げ
screw_w = 6.0;                  // レンズ止めねじ突起の逃げ: 幅 (頭 約3)
screw_d = 3.0;                  // 同: 角穴の上辺 (+y) からの深さ

/* [ケース] */
in_x = 21.8;  in_y = 19.8;      // 内側の半幅
wall = 2.0;   front_t = 2.0;  back_t = 2.5;  corner_r = 3.0;

/* [スナップフック] */
hk_w = 10;  hk_t = 1.4;  hk_gap = 0.25;  hk_catch = 0.7;  hk_zc = 12;

/* [ケーブル出口] */
// コネクタ端 → 4本線 約15 → 細い被覆 10 → 太さ 5 の部分。
// 細い被覆を前板の舌と背面で挟む。太い部分は外に残り、抜け止めになる。
sleeve_d = 4.0;        // 細い被覆の径 (写真からの推定、要実測)
sleeve_squeeze = 0.1;  // 穴を径より小さくする量
cab_x = 9;             // コネクタから横に離し、4本線の長さを内側で使う
cab_z = 12.8;          // 穴の中心の高さ
tongue_w = 8.0;

/* [ファインダー筒] */
col_len = 27.75;  col_wall = 3.0;  col_fillet = 5;
n_slit = 3;  slit_w = 2.0;  slit_len = 20;

$fn = 96;
e = 0.01;

out_x = in_x + wall;  out_y = in_y + wall;
z_pcb = front_t + boss_h;                 // 基板表面
z_in  = z_pcb + pcb_t + back_gap;         // 奥の内面
z_out = z_in + back_t;                    // 背面の外面
hk_bar = hk_gap + hk_catch;               // かえりの出
hk_xo = in_x - hk_gap;                    // フック外面
col_od = finder_fit + 2*col_wall;

module rrect(hx, hy, h, r) linear_extrude(h) offset(r=r) square([2*(hx-r), 2*(hy-r)], center=true);

module cable_hole()
    translate([cab_x, -out_y - 1, cab_z]) rotate([-90, 0, 0])
        cylinder(d=sleeve_d - sleeve_squeeze, h=wall + 2);

// ---------------- 前板 (レンズ側) ----------------
module hook() {   // +x 側。XZ 断面を Y 方向に押し出す
    translate([0, hk_w/2, 0]) rotate([90, 0, 0]) linear_extrude(hk_w)
        polygon([
            [hk_xo - hk_t - 0.8, front_t - e],
            [hk_xo,              front_t - e],
            [hk_xo,              hk_zc - hk_bar],
            [hk_xo + hk_bar,     hk_zc],          // 抜け止め面 45°
            [hk_xo + hk_bar,     hk_zc + 0.4],
            [hk_xo - 0.2,        hk_zc + 2.4],    // 差し込みの斜面
            [hk_xo - hk_t,       hk_zc + 2.4],
            [hk_xo - hk_t,       front_t + 1.0]   // 根元の面取り
        ]);
}

module front() {
    difference() {
        union() {
            rrect(out_x, out_y, front_t, corner_r);
            for (m = [0, 1]) mirror([m, 0, 0]) hook();
            // 基板ボス
            for (x = [-1, 1], y = [-1, 1])
                translate([x*pitch/2, y*pitch/2, front_t - e]) cylinder(d=5, h=boss_h + e);
            // 位置決めリブ (上側 全幅、下側は舌の左右)
            translate([-14, in_y - 0.2 - 0.9, front_t - e]) cube([28, 0.9, 1.8]);
            translate([-14, -in_y + 0.2, front_t - e]) cube([cab_x - tongue_w/2 + 14, 0.9, 1.8]);
            translate([cab_x + tongue_w/2, -in_y + 0.2, front_t - e]) cube([4, 0.9, 1.8]);
            // ケーブル出口の舌 (先端の半円で被覆を押さえる)
            difference() {
                translate([cab_x - (tongue_w - 0.3)/2, -out_y, front_t - e])
                    cube([tongue_w - 0.3, wall, cab_z - front_t]);
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
    r_i = finder_fit/2;  r_o = col_od/2;  L = col_len;  z0 = z_out;
    difference() {
        rotate_extrude() polygon(concat(
            [[r_i, z0 - e], [r_o + col_fillet, z0 - e]],
            // 根元の凹フィレット
            [for (a = [270:-5:180]) [r_o + col_fillet + col_fillet*cos(a),
                                     z0 + col_fillet + col_fillet*sin(a)]],
            [[r_o, z0 + L - 3], [r_o + 0.6, z0 + L - 2], [r_o + 0.6, z0 + L - 0.6],
             [r_o, z0 + L], [r_i + 0.8, z0 + L],              // 入口の面取り
             [r_i, z0 + L - 0.8],
             // 爪の先端の内側の当たり
             [r_i, z0 + L - 1.5], [r_i - pad_interf, z0 + L - 2.5],
             [r_i - pad_interf, z0 + L - 5], [r_i, z0 + L - 6]]
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
        // 背面の抜き穴 (筒の底は接眼部の突き当て)
        translate([0, 0, z_in - 1]) cylinder(d=20, h=back_t + 2);
        // フックの窓
        for (s = [-1, 1])
            translate([s*(in_x + wall/2) - (wall + 1)/2, -hk_w/2 - 0.3, hk_zc - 0.75])
                cube([wall + 1, hk_w + 0.6, 3.4]);
        // ケーブル出口: 開口側から舌の幅の溝、その奥に半円
        translate([cab_x - tongue_w/2, -out_y - 1, front_t - 1])
            cube([tongue_w, wall + 2, cab_z - front_t + 1]);
        cable_hole();
        // こじ開け溝
        for (s = [-1, 1])
            translate([s*out_x - 1.2, 7, front_t - e]) cube([2.4, 6, 1.2]);
    }
}

// ---------------- 確認リング ----------------
module test_rings() {
    for (i = [0:2]) let(d = 27.0 + 0.25*i)
        translate([i*38, 0, 0]) difference() {
            cylinder(d=d + 2*col_wall, h=6);
            translate([0, 0, -1]) cylinder(d=d, h=8);
            for (k = [0:i]) rotate([0, 0, k*14]) translate([d/2 + col_wall, 0, -1]) cylinder(d=2, h=8); // 刻み数 1,2,3
        }
}

module pcb_mock() {
    translate([-pcb/2, -pcb/2, z_pcb]) cube([pcb, pcb, pcb_t]);
    translate([-8, -8, z_pcb - 14.5]) cube([16, 16, 14.5]);
    translate([-12, -2, z_pcb - 4]) cube([24, 4, 4]);
    translate([0, 0, z_pcb - 24]) cylinder(d=14, h=10);
    translate([-10, -15.6, z_pcb + pcb_t]) cube([10, 5.2, 9]);   // 4 ピン + プラグ
    // 細い被覆 10 と太い部分
    translate([cab_x, -out_y, cab_z]) rotate([-90, 0, 0]) cylinder(d=sleeve_d - sleeve_squeeze, h=10);
    translate([cab_x, -out_y, cab_z]) rotate([90, 0, 0]) cylinder(d=5, h=10);
}

if (PART == "front") front();
else if (PART == "back") translate([0, 0, -front_t]) back();
else if (PART == "test_rings") test_rings();
else if (PART == "assembly") { color("gold") front(); color("orange", 0.5) back(); color("green") pcb_mock(); }
else if (PART == "section") difference() {
    union() { color("gold") front(); color("orange") back(); color("green") pcb_mock(); }
    translate([0, -60, -30]) cube([60, 120, 100]);
}
else {  // 印刷配置: 前板は外面を下、背面は開口を下 (内側にサポート要)
    front();
    translate([2*out_x + 8, 0, -front_t]) back();
}
