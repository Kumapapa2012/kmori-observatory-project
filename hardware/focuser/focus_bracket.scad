// フォーカス電動化: セル外周クランプ + 揺動腕 (1218 ウォームギアモーター用)。初版・レンダリング未確認。2026-11-22
// 単位 mm。座標: 原点 = 後部セルの中心、z=0 = セル背面、+z が後ろ (カメラ側)。
// 鏡筒を水平にして後ろから見て、+x = 右 (フォークのアーム側)、+y = 上。軸は右 (3 時) にある。
//
// 実測 (ユーザー):
//   セルのフランジ Ø109、その前の鏡筒本体 Ø105。フランジ外周の平らな部分 11.5、背面側の角は R2 (目視)。
//   軸の中心からセルの中心まで 40.5。軸の表面から接眼部リングまで 6 (リング半径 ≒ 28.5)。
//   台座の上面からセル背面まで 110 (最小。鏡筒の取付位置で変わる)。
//   モーター: 1218 ウォーム (面 12×18、厚み 10、缶の長さ 15.1、軸は面に垂直 Ø3 の D カットで突き出し 8)。
// 構成 (part で切り替え):
//   A   = 右半分のクランプ + 腕の支え (ピボットの柱、リブ、スイッチと張りネジのブロック)
//   B   = 左半分のクランプ
//   ARM = 揺動腕 (モーターを差し込む受け)。プレートを下にした印刷向き
//   BAR = モーターの押さえ板。受けの壁に M2 のタッピングネジ 2 本で留める
//   all = 組み立てた確認用 (arm_deg で張った/緩めた状態を見る)
// 仕組み: 腕はモーターごと、ピボット (M3 ネジ) のまわりに回る。ばねは無い。O リングの張力が腕をハブ側へ引き、
//   内側のブロックの M4 張りネジが腕を外側へ押して O リングを張る。ネジを 2 回転ほど戻すと、腕が内側へ寄って
//   ベルトが緩み、手でノブを回せる。緩めた腕はスイッチのレバーを押す。スイッチは NC 接点で使い、押される (緩い) と
//   開く。「開 = セットされていない」とすれば、断線でも安全側になる。接点はドライバーの有効端子にも直列に入れる。
// モーターの向き: 軸の位置を、セル中心と軸を結ぶ直線 (半径方向) に対して直角に置く (接線方向、6 時側)。
//   縁からのはみ出しは、モーターで約 9.5、腕の外壁で約 13、ピボットの柱で約 14。アームと反対側。
// 確認が必要 (すべて未確認):
//   * OpenSCAD での描画。数値は別途 2 次元の計算で、干渉の隙間を確認した (腕とハブ 20 以上、支えとリング 1.5 以上)
//   * 接眼部リングの軸方向の出っ張りと、カメラ本体の位置。支えの内側のブロック (半径 30 付近) が当たるか
//   * 段ボールのモックで、鏡筒を高度の全域で動かしたときのアーム側や台座との干渉
//   * スイッチ (D2F-01L 想定、sw_* は実物で確認する)。レバーの先端が、緩めた腕に 1〜2 押されること
//   * 鏡筒本体の段差の丸みと、アームの金具との干渉。モーターの配線の逃げ (腕の端と柱の間は約 0.5)

$fn = 120;
part = "all";        // "A", "B", "ARM", "BAR", "all"
show_ref = true;     // all のときの参照用の半透明の実物
arm_deg = 0;         // all のときの腕の角度。0 = 張った状態、8.5 = 緩めた状態

// ---- セル ----
flange_d = 109;  neck_d = 105;
rim_flat = 11.5; rim_round = 2;
flat_z1 = -rim_round;            // 平らな部分の後端
flat_z0 = flat_z1 - rim_flat;    // 平らな部分の前端 = フランジ前面 (-13.5)

// ---- クランプ ----
liner   = 1.0;                   // 内側に貼るゴム/フェルトの厚み
bore_d  = flange_d + 2*liner + 0.6;   // 111.6。割りの隙間を詰めると約 1 mm 小さくなって、ゴムを押さえる
bore_r  = bore_d/2;
wall    = 4;
r_out   = bore_r + wall;
ring_z1 = flat_z1 - 0.5;         // 後端
lip_t   = 1.3;
ring_z0 = flat_z0 - lip_t;       // 前端 (爪の前面)
lip_r   = neck_d/2 + 0.7;        // 爪の内半径 (段差の中。鏡筒本体には触れない)
split_gap = 1.5;
ear_w = 6.5;  ear_h = 10;
bolt_d = 4.4;                    // M4 (M4x12 + ナット)
head_d = 8.0; head_depth = 4.0;
nut_af = 7.3; nut_t = 3.4;

// ---- 軸・モーター (1218) ----
shaft_x   = 40.5;                // ハブの中心 (x)。y = 0
hub_r     = 10.0;                // ハブのフランジ Ø20
mot_w = 12.0;  mot_t = 10.0;  mot_len = 33.1;  shaft_off = 4.0;   // 軸は缶の上端から 4
z_face    = 9.9;                 // モーターの面 (軸が出る面)。プーリーの先端 z=1.9 + 軸の突き出し 8
C_nom     = 31;                  // 軸間 (張った状態)
M_x = shaft_x;  M_y = -C_nom;    // モーターの軸の位置
th_arm = atan2(M_y, M_x) - 90;   // 腕の座標: x = 接線方向 (モーターの缶の向き)、y = 半径方向の外向き
L_pv   = 38;                     // モーターの軸からピボットまで (腕の x)

// ---- 腕 ----
cav_w = mot_w + 0.3;  cav_h = cav_w/2;  wall_t = 2;  arm_half = cav_h + wall_t;
wall_z0 = z_face - 2.5;          // 受けの壁の前端
arm_z0  = z_face + mot_t;        // モーターの背面 = プレートの前面
plate_t = 3;  arm_z1 = arm_z0 + plate_t;
x_end   = -4.1 - wall_t;         // 受けの端の壁
x_wall1 = 33;                    // 受けの壁の後端
bar_x = 20;  bar_len = 12;  bar_t = 2;  bar_z = z_face - bar_t/2;

// ---- 支え ----
post_r = 4.5;  foot_r = 6.5;
sup_z0 = z_face;  sup_z1 = arm_z0 - 0.2;
rib_y0 = -16.5;  rib_y1 = -13.5;  blk_y0 = -21.5;
scr_x = 27;  scr_z = (sup_z0 + sup_z1)/2;
sw_x = 13.5;  sw_w = 13.4;  sw_d = 6.2;  sw_h = 7.0;  sw_slot_w = 8;  sw_slot_h = 4.5;   // オムロン D2F-01L (本体 12.8×5.8×6.5) 用のポケット。実物で要確認

// ================= クランプ =================
module ring_solid() {
  difference() {
    union() {
      translate([0, 0, flat_z0]) cylinder(r = r_out, h = ring_z1 - flat_z0);
      translate([0, 0, ring_z0]) cylinder(r = r_out, h = lip_t + 0.01);
    }
    translate([0, 0, flat_z0]) cylinder(r = bore_r, h = ring_z1 - flat_z0 + 0.1);
    translate([0, 0, ring_z0 - 0.1]) cylinder(r = lip_r, h = lip_t + 0.2);
  }
}

module ear(side, sy) {
  x0 = side > 0 ? split_gap/2 : -split_gap/2 - ear_w;
  y0 = sy > 0 ? bore_r + 0.5 : -(r_out + ear_h);
  translate([x0, y0, ring_z0])
    cube([ear_w, r_out + ear_h - bore_r - 0.5, ring_z1 - ring_z0]);
}

module bolt_cuts(side, sy) {
  y = sy * (r_out + ear_h/2);
  z = (ring_z0 + ring_z1)/2;
  translate([0, y, z]) rotate([0, 90, 0]) cylinder(d = bolt_d, h = 40, center = true);
  if (side > 0)
    translate([split_gap/2 + ear_w - head_depth, y, z]) rotate([0, 90, 0])
      cylinder(d = head_d, h = head_depth + 0.1);
  else
    translate([-split_gap/2 - ear_w - 0.1, y, z]) rotate([0, 90, 0])
      cylinder(d = nut_af/cos(30), h = nut_t + 0.1, $fn = 6);
}

module half(side) {
  difference() {
    union() {
      intersection() {
        ring_solid();
        translate([side > 0 ? split_gap/2 : -1000 - split_gap/2, -1000, -1000]) cube([1000, 2000, 2000]);
      }
      for (sy = [1, -1]) ear(side, sy);
    }
    for (sy = [1, -1]) bolt_cuts(side, sy);
  }
}

// ================= 腕まわり =================
// 腕の座標系: 原点 = モーターの軸、x = 缶の向き (接線方向)、y = 半径方向の外向き、z はそのまま
module armframe() { translate([M_x, M_y, 0]) rotate([0, 0, th_arm]) children(); }

// 揺動腕: 缶を前 (-z) から差し込む受け + 背面のプレート + ピボットの穴
module arm() {
  difference() {
    union() {
      translate([x_end, -arm_half, arm_z0]) cube([L_pv - x_end, 2*arm_half, plate_t]);
      translate([L_pv, 0, arm_z0]) cylinder(r = 5, h = plate_t);
      for (s = [-1, 1])
        translate([x_end, s > 0 ? cav_h : -arm_half, wall_z0])
          cube([x_wall1 - x_end, wall_t, arm_z1 - wall_z0]);
      translate([x_end, -arm_half, z_face]) cube([wall_t, 2*arm_half, arm_z1 - z_face]);
    }
    translate([L_pv, 0, arm_z0 - 1]) cylinder(d = 3.4, h = plate_t + 2, $fn = 32);
    for (s = [-1, 1])
      translate([bar_x, s*(cav_h + wall_t/2), bar_z]) rotate([90, 0, 0])
        cylinder(d = 1.8, h = wall_t + 2, center = true, $fn = 24);
  }
}

// 押さえ板: 缶の前面 (z_face) に載せ、受けの壁に M2 のタッピングネジで留める
module bar() {
  difference() {
    translate([bar_x - bar_len/2, -(cav_h - 0.15), z_face - bar_t]) cube([bar_len, 2*(cav_h - 0.15), bar_t]);
    for (s = [-1, 1])
      translate([bar_x, s*(cav_h - 0.15), bar_z]) rotate([90, 0, 0]) cylinder(d = 1.6, h = 8, center = true, $fn = 24);
  }
}

// 固定側の支え: ピボットの柱、柱とリブをつなぐ壁、リブ、スイッチと張りネジのブロック
module support() {
  h_blk = sup_z1 - sup_z0;
  difference() {
    union() {
      translate([L_pv, 0, ring_z0]) cylinder(r = post_r, h = sup_z1 - ring_z0);
      translate([L_pv, 0, ring_z0]) cylinder(r = foot_r, h = ring_z1 - ring_z0);
      translate([L_pv + 3, rib_y0, sup_z0]) cube([3.5, -rib_y0, h_blk]);
      translate([4, rib_y0, sup_z0]) cube([44.5 - 4, rib_y1 - rib_y0, h_blk]);
      translate([sw_x - 7.9, blk_y0, sup_z0]) cube([15.8, rib_y1 - blk_y0, h_blk]);
      translate([scr_x - 6, blk_y0, sup_z0]) cube([12, rib_y1 - blk_y0, h_blk]);
    }
    translate([L_pv, 0, sup_z1 - 10]) cylinder(d = 2.5, h = 11, $fn = 24);     // M3 ピボットの下穴
    translate([scr_x, blk_y0 - 1, scr_z]) rotate([-90, 0, 0])                  // M4 張りネジ
      cylinder(d = 4.3, h = rib_y1 - blk_y0 + 2, $fn = 32);
    translate([scr_x, blk_y0 - 0.1, scr_z]) rotate([-90, 0, 0])                // ナットの溝
      cylinder(d = 7.2/cos(30), h = 3.5, $fn = 6);
    translate([sw_x - sw_w/2, blk_y0 - 0.1, scr_z - sw_h/2]) cube([sw_w, sw_d + 0.1, sw_h]);   // スイッチ (仮)
    translate([sw_x - sw_slot_w/2, blk_y0 + sw_d - 0.1, scr_z - sw_slot_h/2])
      cube([sw_slot_w, rib_y1 - (blk_y0 + sw_d) + 0.2, sw_slot_h]);                           // レバーの窓
  }
}

module partA() { union() { half(1); armframe() support(); } }
module partB() { half(-1); }

// ================= 参照 =================
module ghost() {
  color("gray", 0.25) {
    translate([0, 0, flat_z0]) cylinder(d = flange_d, h = -flat_z0);
    translate([0, 0, flat_z0 - 40]) cylinder(d = neck_d, h = 40);
    cylinder(r = 28.5, h = 30);                                                // 接眼部リング
    translate([shaft_x, 0, 0]) cylinder(d = 12, h = 19);                       // 軸
    translate([shaft_x, 0, 1]) cylinder(r = hub_r, h = 36);                    // ハブ
    armframe() {
      translate([-shaft_off, -mot_w/2, z_face]) cube([mot_len, mot_w, mot_t]); // モーター
      translate([0, 0, 1.9]) cylinder(r = 4.4, h = 7.6);                       // モーター側プーリー
    }
  }
}

if (part == "A") partA();
else if (part == "B") partB();
else if (part == "ARM") translate([0, 0, arm_z1]) rotate([180, 0, 0]) arm();
else if (part == "BAR") translate([0, 0, -(z_face - bar_t)]) bar();
else {
  partA(); partB();
  armframe() translate([L_pv, 0, 0]) rotate([0, 0, arm_deg]) translate([-L_pv, 0, 0]) { arm(); bar(); }
  if (show_ref) ghost();
}
