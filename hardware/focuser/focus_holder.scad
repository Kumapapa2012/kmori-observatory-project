// フォーカス電動化 (同軸方式): FS90R の保持ブラケット (セル背面に面ファスナーで固定)。第 10 版。2026-11-25
//
// 履歴: 第 1 版は台座に置く案、第 2 版はノブの下だけの片持ち、第 3 版は上下 2 か所の門型、第 4 版は穴付きの 1 枚の環 (ユーザー案)、
//   第 5 版は左右の壁を無くして細くした、第 6 版は貼り付け板を円弧状に広げた、第 7 版は脚の根元にフィレットを足した。
// 第 8 版 (ユーザー指示: 第 7 版の根元の「でっぱり」が気持ち悪い): 原因は、脚とフィレットを x 軸に沿った長方形で作っていたため、
//   貼り付け板の帯 (円弧状) から外れ、はみ出した裾が板の縁で垂直に切り落とされて、羽根のような段になっていたこと。
//   脚と根元のフィレットを、セルの中心まわりの円弧に沿う向き (半径方向 = 幅、円周方向 = 長さ) に置き直した。
//   サーボ板 (上端) は、2 本の脚の上端と中央の長方形の凸包にした。
// 第 9 版 (印刷して実機に合わせた結果、寸法は全て OK。ユーザー 2026-11-24): 第 8 版の穴 Ø18.5 は、後ろからはめるときにグリップ (リブの頂点 Ø20.5)
//   を通せず、きつすぎた。ユーザーは穴の周りを削って、貼り付け板をノブの位置で上下の 2 枚に分けた (うまくいった)。これを図面に反映した:
//   ノブの位置で、半径 gap_cut_r の円と、半幅 gap_hw の帯 (半径方向に全幅) を板から抜き、上下 2 枚の板にした。
//   板の回り込みは、ユーザー案で上下に各 110° (合計 220°) に広げた。上下の板は、脚とサーボ板でつながる。
// 第 10 版 (ユーザー指示 2026-11-25: サーボ側のケーブルは、別部品 CLAMP で、サーボ板の後ろの面 (広い側 +y) に押し付け、さらにホットボンドで固定する。
//   交換時は CLAMP をはずし、ホットボンドをはがす): サーボ板の後ろの面 (z=52) の、耳の端 (y=11.0) の外側に、M2×6 木ねじの下穴 Ø1.7 深さ 4 を 2 つ
//   (x=±5.4, y=15.3)。CLAMP は 17 × 7.2 × 厚み 3.5 の板で、下面にケーブルの溝 (幅 4.0、深さ 0.8、y 方向に全長) があり、ケーブル (厚み 1.1) を押し付ける。
//   窓は無く (第 10 版の途中で埋めた)、下面の溝の天井に浅いへこみ (6 × 4、溝の天井から 0.5) がある。ホットボンドは、ケーブルと板に付けてから CLAMP を押し付け、はみ出しとへこみで固める。
//
// 単位 mm。座標: 原点 = ノブの軸の中心、z = セル背面からの距離 (+z が後ろ)。
//   鏡筒を水平にして後ろから見て、+x = 右 (縁側。セルの中心は -x 側に 40.5)、+y = 上。
//
// 構成: セル背面の平らな面に貼る 1 枚の円弧状の板 (z=0〜5、ノブのスリーブを通す穴付き) から、ノブとカップの上下に脚を立て、
//   サーボ板 (軸に垂直、z=47〜52) でつなぐ門型。サーボは後ろ (+z) から差し込み、耳の M2 タッピングビス 2 本 (後ろから) で留める。
//   サーボの長い側 (22.5) は縦 (長い端が下)。短い側 (厚み 12.1) が左右で、リング側 (軸から 12) に当たらない。
//   反力 (ストールで約 0.15 N·m) は、サーボ板 → 上下の脚 → 貼り付け板の横ずれで受ける。
//   強度の見積もり (PETG E=2000 MPa、概算): 耳のビスに約 5.4 N の偶力、脚に各 約 3.4 N の横力。脚の根元の曲げ応力は 約 1 MPa、
//   たわみ 約 0.05 mm で、PETG の強度 (約 40 MPa) の 1/40 以下。左右の壁は強度には不要なので無い。
//   貼り付け板の面 (z=0) に、面ファスナーのフック面を入れる浅いくぼみ。セル背面に貼るのはループ面。穴は開けない。
//   印刷: 貼り付け板の面を下にすると、サーボ板が上下の脚の間を橋渡しする形になり、サポートが要る。
// 部品: part = "HOLDER" (印刷、PETG) | "CLAMP" (ケーブルを押さえる板。印刷は、ねじの頭の側を下に) | "CHECK" (干渉の確認: 面接触以外が空なら干渉なし)
//       | "CHECK_CAM" (カメラとの干渉) | "all" (参照物つきの表示)
//
// 仮値 (すべて要実測): 貼り付け板の範囲 (セル背面の空いている平らな面)、ホーンの厚み、サーボの寸法 (データシートの目視)。
// 未確認: 実物 (背面の平らさ、材質、リングのつまみネジ、架台のハブとの隙間、カメラ本体との隙間)。
// 注意: ホーンとカップを剛に留めているので、サーボの軸とノブの軸のずれは、そのまま拘束になる。
//   開口の余裕は ±0.3 のみ。うまく回らなければ、ホーンとカップの間に柔らかい継ぎ手を足す。

$fn = 60;
part = "all";

// ---- セルとノブ (実測) ----
cell_c = [-40.5, 0];        // セルの中心 (軸から)
flange_r = 54.5;            // フランジ Ø109
ring_r = 28.5;  ring_h = 14;     // ローレットのリング
sleeve_r = 17.5 / 2;  grip_r = 20.5 / 2;
cup_r = 12.45;  cup_face_z = 40.5;   // focus_cup.scad のカップ
camera_r = 25;              // カメラ本体の半径 (ユーザー実測: 直径 50)。z=14 から後ろ。中心はセルの中心と一致と仮定

// ---- 貼り付け板 (仮): セルの中心まわりの円弧状 ----
edge_m = 3;                 // フランジの縁からの余裕
pad_R = flange_r - edge_m;  // 外側の半径 51.5
pad_r_in = ring_r + 1.0;    // 内側の半径 29.5 (ローレットのリングから 1.0 空ける)
pad_ang_up = 110;  pad_ang_dn = 110;   // ノブの方向 (+x) から上下へ回り込む角度 (セルの中心から見て)
gap_hw = 11.0;              // ノブの位置で上下の板を分ける帯の半幅 (グリップの半径 10.25 + 0.75)。後ろからグリップを通す
gap_cut_r = 14.0;           // 帯の中心の円 (ノブの周りの凹み、板の端が凹の円弧になる)
pocket_keepout = 3.5;       // ノブの穴の縁からこの範囲には、面ファスナーのくぼみを作らない (細い帯)
pad_t = 5;
pocket_d = 1.5;             // 面ファスナーのくぼみの深さ
pocket_in = 2.0;            // くぼみの縁からの内側

// ---- サーボ (FS90R、データシート p.2 の目視) ----
sv_w = 12.1;
sv_up = 6.1;  sv_dn = 16.4;
ear_up = 11.0;  ear_dn = 21.3;
ear_hole_up = 8.7;  ear_hole_dn = 19.0;
function zs(s) = cup_face_z + 30.7 - s;     // s = サーボの底からの距離

// ---- サーボ板 ----
plate_side = 3.2;                           // サーボ板の、開口の外側の帯の幅
slot = sv_w / 2 + 0.3;                      // 開口の半幅 (サーボとの隙間 0.3)
ox = slot + plate_side;                     // サーボ板の中央部の半幅
plate_z0 = 47;  plate_z1 = zs(19.2);        // サーボ板の後ろの面は耳の前面 (z=52.0)
plate_y = 19;                               // サーボ板の中央部の半高 (耳のビスの穴 -19.0 まで)

// ---- 脚 (セルの中心まわりの円弧に沿う向きに置く。上の脚を作り、下の脚は y の鏡像) ----
leg_rc = 39.5;              // 脚の中心の、セルの中心からの半径 (貼り付け板の帯の中央 40.5 のやや内側)
leg_hw = 6;                 // 脚の半幅 (半径方向。r=33.5〜45.5)
leg_len = 6;                // 脚の長さ (円周方向)
leg_y = 19;                 // 脚の中心の |y| (カップの半径 12.45 から離す。ノブ側の端は y≈13.5 でカップまで 3 以上)
leg_th = asin(leg_y / leg_rc);   // 脚の中心の、セルの中心から見た角度 (約 28.7°)
// 根元のフィレット (凹の円弧、半径 fil_h)。外側 (円周方向、ノブから離れる向き) へ長く、内側と半径方向へは短く広げる
fil_h = 14;                 // フィレットの高さ (z=5〜19)
fil_out = 14;               // 外側へ広がる長さ
fil_in = 3;                 // 内側 (ノブ側) へ広がる長さ (足元で、グリップ r=10.25 まで 2 以上空く)
fil_side = 3;               // 半径方向 (左右) へ広がる長さ (足元で r=30.5〜48.5。貼り付け板の帯 29.5〜51.5 に収まる)
fil_rc = 3.5;               // 断面の角の丸めの半径 (足元)
fil_n = 14;                 // 高さ方向の分割数

// ---- ケーブルを押さえる板 CLAMP (サーボ板の後ろの面 z=52 の、広い側 +y に M2×6 木ねじ 2 本) ----
cable_w = 3.5;  cable_t = 1.1;             // 平型ケーブルの幅と厚み (ユーザー実測、約)
cl_y0 = 11.7;  cl_len = 7.2;               // y の範囲 (耳の端 y=11.0 から 0.7 空ける。板の縁 y=19 の内側)
cl_hw = 8.5;                               // 板の半幅 (x。サーボ板の半幅 9.35 の内側)
cl_sx = 5.4;  cl_sy = cl_y0 + cl_len / 2;  // ねじの位置 (溝の両脇)
cl_pilot_d = 1.7;  cl_pilot_h = 4;         // 下穴 (サーボ板の厚み 5 の中に深さ 4)
cl_t = 3.5;  cl_clear_d = 2.4;  cl_cb_d = 4.2;  cl_cb_h = 1.2;   // 厚み、逃げ穴、頭のざぐり (ねじは約 3.7 が板に入る)
cl_gw = 4.0;  cl_gd = 0.8;                 // 下面のケーブルの溝: 幅 (ケーブル 3.5)、深さ (ケーブル 1.1 を 0.3 押す)
cl_rw = 6.0;  cl_rl = 4.0;  cl_rd = 0.5;   // 下面の浅いへこみ (溝の天井にさらに掘る。ホットボンドの溜まり): x の幅、y の長さ、溝の天井からの深さ

// ---- 貼り付け板の外形 (2 次元) ----
module sector2d(a0, a1, r = 100) {
    n = 40;
    polygon(concat([[0, 0]], [for (i = [0 : n]) let (a = a0 + (a1 - a0) * i / n) [r * cos(a), r * sin(a)]]));
}
module plate2d() {
    difference() {
        intersection() {
            translate(cell_c) difference() {            // セルの中心まわりの円環 (リングの外 〜 フランジの縁の内側)
                circle(r = pad_R, $fn = 240);
                circle(r = pad_r_in, $fn = 240);
            }
            translate(cell_c) sector2d(-pad_ang_dn, pad_ang_up);   // ノブの方向を中心に、上下へ回り込む扇形
        }
        circle(r = gap_cut_r, $fn = 90);
        translate([-100, -gap_hw]) square([200, 2 * gap_hw]);
    }
}
// 面ファスナーのくぼみの外形: ノブの穴の周りの細い帯を避けた、広い部分 (縁から pocket_in 内側)
module pockets2d() {
    offset(delta = -pocket_in)
        difference() {
            plate2d();
            circle(r = gap_cut_r, $fn = 90);
        }
}

// ---- 脚と根元のフィレット ----
// 上の脚の局所座標: u = 半径方向 (セルの中心から外へ)、v = 円周方向 (角度の増える向き = ノブから離れる向き)。
module leg_local() { translate(cell_c) rotate(leg_th) children(); }
// 上の脚と下の脚 (下は y の鏡像)
module both_legs() { leg_local() children(); mirror([0, 1]) leg_local() children(); }

module stem2d() { translate([leg_rc - leg_hw, -leg_len / 2]) square([2 * leg_hw, leg_len]); }
// 根元のフィレットの 1 断面。t = 1 (足元) 〜 0 (脚の太さ)。角を丸めた長方形
module fil_slice(t) {
    u0 = leg_rc - leg_hw - fil_side * t;
    u1 = leg_rc + leg_hw + fil_side * t;
    v0 = -leg_len / 2 - fil_in * t;
    v1 = leg_len / 2 + fil_out * t;
    rc = fil_rc * t;
    offset(r = rc, $fn = 48) translate([u0 + rc, v0 + rc]) square([u1 - u0 - 2 * rc, v1 - v0 - 2 * rc]);
}
// 凹の円弧 (半径 fil_h) の断面: dz = 0 (足元) で t=1、dz = fil_h で t=0
function fil_t(dz) = (fil_h - sqrt(fil_h * fil_h - (fil_h - dz) * (fil_h - dz))) / fil_h;

module leg_solid_local() {
    // 脚の柱: 貼り付け板からサーボ板の後ろの面まで
    translate([0, 0, pad_t - 0.01]) linear_extrude(height = plate_z1 - pad_t + 0.01) stem2d();
    // 足元のフィレット (貼り付け板の外形からはみ出さないよう、後で貼り付け板の外形と共通部分を取る)
    translate([0, 0, pad_t - 0.5]) linear_extrude(height = 0.51) fil_slice(1);
    for (i = [0 : fil_n - 1]) hull() {
        translate([0, 0, pad_t + fil_h * i / fil_n - 0.005])
            linear_extrude(height = 0.01) fil_slice(fil_t(fil_h * i / fil_n));
        translate([0, 0, pad_t + fil_h * (i + 1) / fil_n - 0.005])
            linear_extrude(height = 0.01) fil_slice(fil_t(fil_h * (i + 1) / fil_n));
    }
}

// サーボ板 (2 次元): 中央の長方形と、2 本の脚の上端の凸包。角を丸める
module servo_plate2d() {
    offset(r = 2, $fn = 48) offset(delta = -2)
        hull() {
            translate([-ox, -plate_y]) square([2 * ox, 2 * plate_y]);
            both_legs() stem2d();
        }
}

// CLAMP (局所: 下面 z=0 がサーボ板に当たる。x は中心、y は 0〜cl_len)。下面の溝は y 方向に全長
module clamp() {
    difference() {
        linear_extrude(height = cl_t) offset(r = 1.5, $fn = 36) offset(delta = -1.5) translate([-cl_hw, 0]) square([2 * cl_hw, cl_len]);
        translate([-cl_gw / 2, -1, -0.01]) cube([cl_gw, cl_len + 2, cl_gd + 0.01]);
        translate([-cl_rw / 2, (cl_len - cl_rl) / 2, -0.01]) cube([cl_rw, cl_rl, cl_gd + cl_rd + 0.01]);
        for (sx = [-1, 1]) translate([sx * cl_sx, cl_len / 2, 0]) {
            translate([0, 0, -1]) cylinder(d = cl_clear_d, h = cl_t + 2, $fn = 24);
            translate([0, 0, cl_t - cl_cb_h]) cylinder(d = cl_cb_d, h = cl_cb_h + 1, $fn = 32);
        }
    }
}
module clamp_placed() { translate([0, cl_y0, plate_z1]) clamp(); }

module holder() {
    difference() {
        union() {
            // 貼り付け板
            linear_extrude(height = pad_t) plate2d();
            // 脚と足元のフィレット (足元は貼り付け板の外形に収める)
            intersection() {
                union() both_legs() leg_solid_local();
                union() {
                    linear_extrude(height = pad_t + fil_h + 0.01) plate2d();                         // 足元のフィレットの範囲
                    translate([0, 0, pad_t + fil_h]) linear_extrude(height = plate_z1) offset(delta = 20) plate2d();   // 柱の上の部分は制限しない
                }
            }
            // サーボ板 (門の梁)。左右の壁は無し
            translate([0, 0, plate_z0]) linear_extrude(height = plate_z1 - plate_z0) servo_plate2d();
        }
        // サーボ本体 (上部) が通る開口
        translate([-slot, -sv_dn - 0.3, plate_z0 - 1])
            cube([2 * slot, sv_dn + sv_up + 0.6, plate_z1 - plate_z0 + 2]);
        // 耳のタッピングビス (M2) の下穴: 後ろの面から深さ 4
        for (y = [ear_hole_up, -ear_hole_dn])
            translate([0, y, plate_z1 - 4]) cylinder(d = 1.7, h = 4.01, $fn = 24);
        // CLAMP の下穴 (サーボ板の後ろの面から、深さ cl_pilot_h)
        for (sx = [-1, 1]) translate([sx * cl_sx, cl_sy, plate_z1 - cl_pilot_h])
            cylinder(d = cl_pilot_d, h = cl_pilot_h + 0.01, $fn = 24);
        // 面ファスナーのくぼみ (貼り付け板の、セルに向く面 z=0)
        translate([0, 0, -0.01]) linear_extrude(height = pocket_d + 0.01)
            pockets2d();
    }
}

// ---- 参照物 (出力しない) ----
module servo_ref() {
    translate([-sv_w / 2, -sv_dn, zs(16.7)]) cube([sv_w, sv_dn + sv_up, 16.7]);
    translate([-sv_w / 2, -ear_dn, zs(19.2)]) cube([sv_w, ear_dn + ear_up, 2.5]);
    translate([-sv_w / 2, -sv_dn, zs(23.4)]) cube([sv_w, sv_dn + sv_up, 4.2]);
    hull() {
        translate([0, 0, zs(27.7)]) cylinder(r = 6, h = 4.3);
        translate([0, -8.5, zs(27.7)]) cylinder(r = 6, h = 4.3);
    }
    translate([0, 0, zs(30.7)]) cylinder(r = 2.4, h = 3.0);
    translate([0, 0, zs(30.7)]) cylinder(r = 11, h = 3.0);   // ホーン (円板で代用)
}
module cup_ref() { translate([0, 0, 16]) cylinder(r = cup_r, h = cup_face_z - 16); }
module knob_ref() {
    cylinder(r = sleeve_r, h = 12);
    translate([0, 0, 12]) cylinder(r = grip_r, h = 25);
}
module ring_ref() { translate(cell_c) cylinder(r = ring_r, h = ring_h); }
module cell_ref() { translate([cell_c[0], cell_c[1], -14]) cylinder(r = flange_r, h = 14); }
module camera_ref() { translate([cell_c[0], cell_c[1], ring_h]) cylinder(r = camera_r, h = 80); }

if (part == "HOLDER") holder();
else if (part == "CLAMP") clamp();
else if (part == "CHECK_CL") {
    intersection() { clamp_placed(); holder(); }
    intersection() { clamp_placed(); servo_ref(); }
    intersection() { clamp_placed(); cup_ref(); }
    intersection() { clamp_placed(); ring_ref(); }
    intersection() { clamp_placed(); knob_ref(); }
} else if (part == "CHECK") {
    intersection() { holder(); servo_ref(); }
    intersection() { holder(); cup_ref(); }
    intersection() { holder(); knob_ref(); }
    intersection() { holder(); ring_ref(); }
    intersection() { holder(); cell_ref(); }
} else if (part == "CHECK_CAM") {
    intersection() { holder(); camera_ref(); }
} else {
    holder();
    color("green", 0.7) clamp_placed();
    color("orange", 0.6) servo_ref();
    color("gray", 0.4) cup_ref();
    color("gray", 0.4) knob_ref();
    color("brown", 0.3) cell_ref();
    color("blue", 0.2) ring_ref();
}
