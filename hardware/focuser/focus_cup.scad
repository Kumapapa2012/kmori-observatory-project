// フォーカス電動化 (同軸方式): ノブにかぶせるカップ。初版。2026-11-23
// 単位 mm。座標: 原点 = ノブの軸の中心、z = セル背面からの距離 (+z が後ろ)。
//
// 方式 (ユーザー決定 2026-11-23): FS90R を軸の後ろに同軸で置き、ホーンにつないだカップをノブのグリップにかぶせて回す。
//   カップの内側は、グリップのリブ (丸い山、幅 2、高さ 1.0、10 本) に合う溝。滑らずにトルクが伝わる。
//   カップはローレットのリング (z=0〜14) を避け、z=16 からグリップの先端 z=37 までかぶせる (かかり 21)。
//   サーボ本体の固定 (反力受け) はこのファイルの対象外 (focus_clip.scad の爪の流用を検討中)。
//
// グリップの実測 (ユーザー 2026-11-23): 谷の底 Ø18.5、リブの頂点 Ø20.5、リブの本数 10、リブは丸い山で幅 2。
//   リブの高さ 1.0 と幅 2 から、リブの断面を「谷の円周上に中心を置いた半径 1 の円」として扱う (半円)。
// 部品: part = "TEST" (はめあい確認用の短いリング。まずこれを刷る) | "CUP" (本体) | "all"
// 未確認 (すべて):
//   * OpenSCAD での 3 次元の干渉は下の check で確認。実物へのはめあい (隙間 clr) は未確認。FDM の公差で 0.25 を仮置き
//   * リブの実際の断面 (半円か、頂点が丸い台形か)。TEST で確かめる
//   * ホーンの固定穴 (十字ホーンの Ø11.8 の円、Ø1.2) と、ホーン中央のネジの頭の逃げ。データシートの目視で、実物で要確認
//   * リング側の端 (z=16) の外側が、リングやカメラ側の部品に当たらないか (外径 約 Ø25)

$fn = 120;
part = "all";

// ---- 実測 ----
grip_base_r = 18.5 / 2;     // 谷の底
rib_tip_r = 20.5 / 2;       // リブの頂点
rib_n = 10;
rib_w = 2.0;                // リブの幅 (根元)
rib_h = rib_tip_r - grip_base_r;   // 1.0
rib_rc = rib_w / 2;         // 半円の半径 = 1.0 (高さ 1.0 と一致)
grip_z0 = 16;               // かぶせ始め (リングの上 14 より 2 上)
grip_z1 = 37;               // グリップの先端

// ---- 設計値 ----
clr = 0.25;                 // 半径方向の隙間 (FDM の仮置き)
wall = 2.0;                 // カップの壁の厚み
floor_t = 3.0;              // 底の厚み
end_gap = 0.5;              // グリップの先端と底の隙間
cup_r = rib_tip_r + clr + wall;       // 外半径 約 12.5

// ホーンの固定 (十字ホーン、Ø11.8 の円に Ø1.2 の穴、4 か所を想定)
horn_pcd_r = 11.8 / 2;
horn_hole_d = 1.0;          // タッピングビス用の下穴
horn_head_pocket_d = 6.0;   // ホーン中央のネジの頭の逃げ
horn_head_pocket_h = 2.0;

// グリップ断面 (2 次元): 谷の円 + 10 個の半円のリブ
module grip2d() {
    circle(r = grip_base_r);
    for (i = [0 : rib_n - 1])
        rotate(i * 360 / rib_n)
            translate([grip_base_r, 0]) circle(r = rib_rc, $fn = 48);
}

// ボア (グリップ + 隙間)
module bore2d() { offset(r = clr) grip2d(); }

module cup() {
    z_floor0 = grip_z1 + end_gap;
    difference() {
        union() {
            // 筒: z = grip_z0 〜 底の上面
            translate([0, 0, grip_z0])
                cylinder(r = cup_r, h = z_floor0 + floor_t - grip_z0);
        }
        // ボア
        translate([0, 0, grip_z0 - 0.01])
            linear_extrude(height = z_floor0 - grip_z0 + 0.01) bore2d();
        // 底の外面: ホーンの穴と、中央のネジ頭の逃げ
        translate([0, 0, z_floor0 + floor_t - horn_head_pocket_h])
            cylinder(d = horn_head_pocket_d, h = horn_head_pocket_h + 0.01, $fn = 48);
        for (i = [0 : 3])
            rotate(45 + i * 90)
                translate([horn_pcd_r, 0, z_floor0 - 0.01])
                    cylinder(d = horn_hole_d, h = floor_t + 0.02, $fn = 24);
    }
}

// はめあい確認用の短いリング: かかり 8
module test_ring() {
    translate([0, 0, 0])
        linear_extrude(height = 8)
            difference() { circle(r = cup_r); bore2d(); }
}

// グリップ (確認用の参照物。出力しない)
module grip_ref() {
    translate([0, 0, grip_z0]) linear_extrude(height = grip_z1 - grip_z0) grip2d();
}

if (part == "CUP") cup();
else if (part == "TEST") test_ring();
else if (part == "CHECK") intersection() { cup(); grip_ref(); }   // 空なら干渉なし
else {
    cup();
    color("gray", 0.5) grip_ref();
}
