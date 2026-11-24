// フォーカス電動化: ノブに直接作用するクリップ + FS90R 連続回転サーボ。初版・レンダリング未確認。2026-11-23
// 単位 mm。座標: 原点 = ノブの軸の中心 (K)、z = セル背面からの距離 (+z が後ろ)。
//   鏡筒を水平にして後ろから見て、+x = 右 (縁側。セルの中心は -x 側に 40.5)、+y = 上。
//
// 方式:
//   クリップはノブのグリップの「リブの無い滑らかな帯」(Ø18.5、z=12〜16) を、車輪 1 個とピン 2 個で挟む。
//   車輪は 3 時側 (縁側)、ピンは ±120° (左上と左下)。左 (リング・カメラ側) が開口。クリップは右から左へ押し込む。
//   車輪はサーボの出力軸 (十字ホーン) に付き、グリップに直接当たる。滑りすぎるときは押し付けを増やす。
//   サーボはクリップの板に、出力軸をセル側へ向けて後ろから差し込み、耳を M2 のネジ 2 本で留める。
//   反力はクリップの 2 本の爪が、フランジ外周 (平らな部分 z=-13.5〜-2) に、上下の ±45° で外から当たって受ける。
//   (ノブとクリップの間だけでは正味のトルクがかからないので、固定点が必要。)
// 部品: part = "CLIP" | "WHEEL" | "all"。印刷は PETG。CLIP は爪の向き (z 方向の棒を立てる) で刷る。
// 未確認 (すべて):
//   * OpenSCAD での描画。ここの数値は 2 次元の手計算のみ
//   * サーボの寸法は、データシート p.2 の図面と寸法線から読んだ (軸は厚みの中央、本体の端まで 6.1 と 16.4、耳の穴 27.7 間隔)。
//     本体の外側 (軸から x=-6.05..+6.05) は、グリップのリブ (半径 10.25) まで 1.2 しかない。十字ホームの厚みと tip_z は仮
//   * 架台の蟻溝の受けとの隙間 (3 時、フランジ外周で約 3.5)。爪は ±45° なので当たらない見込みだが、要確認
//   * 軸の右 45 mm 以内に架台の面は無い、という聞き取り (サーボの外側は 軸から約 26、板は約 30)
//   * 押し付け力 (pin_int、tire_int)。ピンの食い込みで決まる。ノブのトルクは未測定
//   * リング (セル背面から 14、軸の中心から 12) との隙間は、左側の開口で避けた (ピンの外側は 7 以上)

$fn = 90;
part = "all";        // "CLIP" | "CLIP_PRINT" (印刷向き) | "WHEEL" | "all"
show_ref = true;

// ---- 実測 ----
sx = 40.5;                 // セル中心から軸まで
rim_r = 54.5;              // フランジ Ø109 の平らな部分
flat_z0 = -13.5;  flat_z1 = -2.0;
band_r = 18.5/2;           // 滑らかな帯 Ø18.5±0.1
band_z0 = 12;  band_z1 = 16;
rib_r = 20.5/2;            // リブの頂点
grip_z1 = 37;
sleeve_r = 17.5/2;
ring_r = 28.5;  ring_h = 14;   // セルの中心から。ローレットのリング

// ---- 車輪 ----
tire_cs = 1.5;             // O リングの線径
tire_r = 8.5;              // 車輪の接触半径 (O リング込み)。外径 Ø17
tire_int = 0.25;           // 食い込み
wheel_w = 3.5;
tip_z = 14.3;              // サーボ出力軸の先端の z (想定)
wheel_zc = tip_z - 0.25;   // 車輪の中心の z (z=12.3〜15.8 で、滑らかな帯に収まる)
horn_hole_r = 5.9;         // 十字ホームの穴の円 Ø11.8 (Ø1.2、データシートを目視)
d_w = band_r + tire_r - tire_int;   // 軸から車輪の中心まで

// ---- ピンとばね腕 ----
// 腕は背が高い (z=12〜板の下) 薄い板ばね。背を高くして剛性を稼ぎ、厚みを薄くしてひずみを抑える。
// 根元が太く先が細いテーパーで、応力を腕全体に散らす。根元は柱とつなぐ所に大きな丸み (rnd の concave) を付ける。
// 試算 (PETG E=2000MPa、円弧ばねのエネルギー法、概算 ±30%): 食い込み 0.6 で 1 本 約 9N、車輪の押し付け 約 6N、
//   はめ込み時の最大ひずみ 約 2%、はめ込みの力 約 20N (1 本)。ねじれ・曲げは README のコメント参照
pin_r = 1.5;
pin_int = 0.6;
pin_a = 110;
pin_rc = band_r + pin_r - pin_int;
arm_r0 = pin_rc + pin_r - 0.4;           // 腕の内面。ピンの外側に 0.4 食い込ませてつなぐ
t_root = 2.4;  t_tip = 1.5;              // 腕の厚み (根元 → 先)
arm_a0 = 45;  arm_a1 = pin_a + 6;        // 上の腕 (下は鏡像)
arm_top = 22.8;                          // 腕の上端 (板の下まで届かせる)
r_convex = 0.6;  r_concave = 3.0;        // 腕まわりの丸み: 角を丸める半径、入り隅のフィレット半径
r_plate_convex = 2.5;  r_plate_concave = 3.0;


// ---- サーボ FS90R (データシートから) ----
sv_t = 12.1;  sv_len = 22.5;
// データシート p.2 の図面から: 軸は厚み 12.1 の中央 (両側 6.05)。耳の穴 (Ø2.2、先端が開いた溝) は軸を通る線上にあり、
// 穴の間隔 27.7、軸から一方の穴まで 8.7 (もう一方へ 19.0)。耳の先端は穴から 2.3 先 (全長 32.3)。
// よって本体の端までは、軸から 8.7 - (32.3-22.5)/2 + (32.3-27.7)/2 = 6.1 と 16.4。
sv_side_in = sv_t/2;  sv_side_out = sv_t/2;
ear_a = 8.7;  ear_b = 27.7 - 8.7;                 // 軸から耳の穴まで (y の負側 / 正側)
sv_end_a = ear_a - (32.3 - sv_len)/2 + (32.3 - 27.7)/2;   // 6.1
sv_y0 = -sv_end_a;  sv_y1 = sv_len - sv_end_a;
ear_hole_dy0 = -ear_a;  ear_hole_dy1 = ear_b;
// 先端から: ボス上 +3、ケース前面 +7.3、耳の前面 +11.5、耳の後面 +14、本体の後端 +30.7 (先端は -z 側)
ear_front = tip_z + 11.5;

// ---- 板・柱・爪 ----
pz0 = ear_front - 3;  pz1 = ear_front;     // 板。耳の前面が板の後ろの面に当たる
px0 = 7.0;  px1 = d_w + sv_side_out + 4;
py0 = -13.6;  py1 = sv_y1 + 6;
notch_r = rib_r + 1.2;                      // グリップのリブを避ける
pil_x0 = 7.0;  pil_x1 = 10.8;  pil_y0 = 9.6;  pil_y1 = 13.6;
claw_a = 45;                                // 爪の位置 (セル中心まわりの角、上下)
ft = 3.5;  fw = 12;                         // 爪の棒: 半径方向 3.5 (受けの隙間 約 3.5 以下)、幅 12
pad_gap = 0.3;                              // 外周との隙間。フェルト 1 mm を貼って、押し当たるようにする
claw_z0 = -10;                              // 爪の下端 (平らな部分 z=-13.5〜-2 の内)

module sector(r0, r1, a0, a1, n = 30) {
  polygon(concat(
    [for (i = [0:n]) let(a = a0 + (a1 - a0)*i/n) [r1*cos(a), r1*sin(a)]],
    [for (i = [n:-1:0]) let(a = a0 + (a1 - a0)*i/n) [r0*cos(a), r0*sin(a)]]));
}
// 厚みが線形に変わる腕 (外半径が根元 r0+t0 → 先 r0+t1)
module arm_taper(r0, t0, t1, a0, a1, n = 40) {
  polygon(concat(
    [for (i = [0:n]) let(a = a0 + (a1 - a0)*i/n, r = r0 + t0 + (t1 - t0)*i/n) [r*cos(a), r*sin(a)]],
    [for (i = [n:-1:0]) let(a = a0 + (a1 - a0)*i/n) [r0*cos(a), r0*sin(a)]]));
}
// 2 次元の角丸め: 出隅を rv、入り隅を rc の半径で丸める (接合部の面は丸めない所で使う)
module rnd(rv, rc) { offset(r = -rc) offset(delta = rc) offset(r = rv) offset(delta = -rv) children(); }
module rnd_convex(rv) { offset(r = rv) offset(delta = -rv) children(); }

// 爪の足の平面形: フランジ外周に沿った円弧 (曲面で当たる)。セル中心まわりの角 a
claw_w_deg = (fw/2) / (rim_r + pad_gap) * 180 / PI;
module claw2d(a) {
  translate([-sx, 0]) rotate(a) sector(rim_r + pad_gap, rim_r + pad_gap + ft, -claw_w_deg, claw_w_deg, 12);
}

// 先端と根元が丸い (端面が球面状に面取りされた) ピン
module pin3d() {
  h = band_z1 - band_z0;
  rotate_extrude() intersection() {
    offset(r = 0.7) offset(delta = -0.7) translate([-pin_r, 0]) square([2*pin_r, h]);
    square([pin_r, h]);
  }
}

module clip() {
  difference() {
    union() {
      // (A) ばね腕と柱。背の高い板ばね。根元の入り隅と先の角は丸める
      translate([0, 0, band_z0]) linear_extrude(arm_top + 0.4 - band_z0)
        rnd(r_convex, r_concave) {
          for (s = [1, -1]) scale([1, s]) {
            arm_taper(arm_r0, t_root, t_tip, arm_a0, arm_a1);
            translate([pil_x0, pil_y0]) square([pil_x1 - pil_x0, pil_y1 - pil_y0]);
          }
        }
      // ピン (グリップの帯に当たる。端は丸い)
      for (s = [1, -1]) translate([pin_rc*cos(pin_a), s*pin_rc*sin(pin_a), band_z0]) pin3d();
      // (B) サーボを受ける板と、爪へつなぐ斜めの帯。外形は丸める
      translate([0, 0, pz0]) linear_extrude(pz1 - pz0)
        rnd(r_plate_convex, r_plate_concave) {
          difference() { translate([px0, py0]) square([px1 - px0, py1 - py0]); circle(r = notch_r); }
          for (s = [1, -1]) {
            claw2d(s*claw_a);
            hull() {
              translate([px0, s > 0 ? py1 - 0.6 : py0]) square([px1 - px0, 0.6]);
              claw2d(s*claw_a);
            }
          }
        }
      // (C) 爪の棒 (板からフランジの平らな部分まで)。縦の角は丸める。外周に当たる面はそのまま
      for (s = [1, -1])
        translate([0, 0, claw_z0]) linear_extrude(pz1 - claw_z0) rnd_convex(1.0) claw2d(s*claw_a);
    }
    // サーボのポケット (後ろから差し込む。耳は板の後ろの面に乗る)
    translate([d_w - sv_side_in - 0.2, sv_y0 - 0.2, pz0 - 1]) cube([sv_t + 0.4, sv_len + 0.4, pz1 - pz0 + 2]);
    // 耳の M2 ネジの下穴 (後ろから入れて板の中で止める)
    for (y = [ear_hole_dy0, ear_hole_dy1]) translate([d_w, y, pz0 + 0.6]) cylinder(d = 1.7, h = pz1 - pz0, $fn = 24);
  }
}



// 車輪。z=0 が前面 (セル側)、+z がサーボ側。ホーンの穴にピンを差し、瞬間接着剤で留める (ホーンの面に貼る)
wheel_root_r = tire_r - tire_cs;            // O リングの線径を変えても、接触半径 tire_r は変えない
wheel_flange_r = wheel_root_r + 1.0;
wheel_fl_t = (wheel_w - (tire_cs + 0.3))/2;
assert(wheel_root_r > horn_hole_r + 0.8, "O リングの線径が太すぎる (ホーンの穴の円に届く)");
module wheel() {
  difference() {
    union() {
      // 溝の底の半径 = 接触半径 - O リングの線径 (線径 1.5 なら 7.0)。縁の半径は底 + 1.0。溝の幅は線径 + 0.3
      rotate_extrude() polygon([[0,0],[wheel_flange_r,0],[wheel_flange_r,wheel_fl_t],[wheel_root_r,wheel_fl_t],
        [wheel_root_r,wheel_w - wheel_fl_t],[wheel_flange_r,wheel_w - wheel_fl_t],[wheel_flange_r,wheel_w],[0,wheel_w]]);
      for (s = [1, -1]) translate([s*horn_hole_r, 0, wheel_w - 0.1]) cylinder(d = 1.1, h = 1.6, $fn = 20);
    }
    translate([0, 0, -0.1]) cylinder(d = 6.5, h = wheel_w + 0.2, $fn = 40);   // 中央は貫通 (ホーンのハブとネジ頭が入る)
  }
}

module ghost() {
  color("silver", 0.5) {
    translate([0, 0, 1]) cylinder(r = sleeve_r, h = band_z0 - 1);
    translate([0, 0, band_z0]) cylinder(r = band_r, h = band_z1 - band_z0);
    translate([0, 0, band_z1]) cylinder(r = rib_r, h = grip_z1 - band_z1);
  }
  color("gray", 0.25) {
    translate([-sx, 0, flat_z0]) cylinder(r = rim_r, h = flat_z1 - flat_z0);
    translate([-sx, 0, 0]) difference() { cylinder(r = ring_r, h = ring_h); translate([0, 0, -1]) cylinder(r = ring_r - 3, h = ring_h + 2); }
  }
  color("steelblue", 0.5) {
    translate([d_w - sv_side_in, sv_y0, tip_z + 7.3]) cube([sv_t, sv_len, 30.7 - 7.3]);
    translate([d_w - sv_side_in, sv_y0 - 4.9, tip_z + 11.5]) cube([sv_t, 32.3, 2.5]);
    translate([d_w, 0, tip_z + 3]) cylinder(r = 6, h = 4.3);                                  // ギヤ室 (ケース上面の盛り上がり): 半径 6 の円
    translate([d_w - 2.5, 0, tip_z + 3]) cube([5, 8.5, 4.3]);                                  // 長い端側へ 8.5 張り出す (図面を目視)
    translate([d_w, 0, tip_z]) cylinder(d = 4.86, h = 3.3);
  }
}

if (part == "CLIP" || part == "all") clip();
if (part == "WHEEL") wheel();
// 印刷向き: 板の後ろの面 (耳が乗る面) をベッドに付け、爪の棒と腕を上へ立てる。支えはほぼ不要 (ピンの下だけ小さな張り出し)
if (part == "CLIP_PRINT") translate([0, 0, pz1]) rotate([180, 0, 0]) clip();
if (part == "all") {
  translate([d_w, 0, wheel_zc - wheel_w/2]) wheel();
  if (show_ref) ghost();
}

// 確認用の出力
echo(str("車輪の中心 d_w=", d_w, ", ピンの中心 r=", pin_rc, ", ピンの内側の間隔=", 2*pin_rc*sin(pin_a) - 2*pin_r));
echo(str("サーボの外側の端 x=", d_w + sv_side_out, " (縁 ", rim_r - sx, " より ", d_w + sv_side_out - (rim_r - sx), " 外)"));
