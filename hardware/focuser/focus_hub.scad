// フォーカス軸用「ベルト溝付きノブ」(ハブ) 初版。2026-11-22
// 単位 mm。z=0 が開口端 (後部セル側)、+z が先端。
//
// 実測 (ユーザー):
//   軸: 真鍮、段付き。セル側の細い部分 Ø9.4 長 9、先端側の太い部分 Ø12 長 10、全長 19。D カットなし。
//   元のノブ: スリーブ外径 17.5 / 内径 12、M3 止めネジ 2 本、グリップ径 18.6、全長 約 37 (写真からの概算)。
//   軸の表面から接眼部リングまで 6 mm -> 軸中心から 12 mm。
// 未確認: 元のノブがセル面のどこまで寄っていたか (CELL_GAP は仮)、O リングの線径、レンダリング確認。
//
// 使い方: OpenSCAD で開き、F6 → STL を書き出す。最初は壁を 4 周、充填 40% 以上で試し刷りして、
//         12 mm 軸への入り具合 (BORE_D) と止めネジの効きを見る。きつければ BORE_D を上げる。

$fn = 96;

// ---- 軸 (実測) ----
shaft_thick_d   = 12.0;
shaft_len       = 19.0;   // セル面から先端まで
shaft_thick_len = 10.0;
ring_gap        = 6.0;    // 軸の表面からリングまで
ring_r          = shaft_thick_d/2 + ring_gap;   // 軸中心からリングまで = 12

// ---- ハブ ----
cell_gap    = 1.0;        // 開口端とセル面の隙間 (仮)
bore_d      = 12.25;      // 12 mm 軸 + FDM の余裕
bore_depth  = shaft_len - cell_gap + 0.6;       // 先端に 0.6 の逃げ
length      = 36.0;       // 元のノブの全長 ≒ 37 に合わせる
grip_r      = 18.6/2;
flange_r    = 20.0/2;     // ノブ (Ø18.6) より大きい。リング (軸中心から 12) との隙間 2 mm が上限 (ユーザー決定 Ø21 以内)
root_r      = 8.5;        // V 溝の底 Ø17。底の肉厚 = 8.5 - 6.125 = 2.4
g0 = 1.0;  g1 = 5.6;      // 溝の幅 (フランジの内側)
root_w      = 0.8;
flange2_end = 7.0;
oring_cs    = 1.5;        // O リング線径 (想定)。モーター側の小プーリーで曲げやすい細さ。中心円は約 Ø18.3

// ---- 止めネジ M3 ----
screw_z      = (shaft_len - shaft_thick_len/2) - cell_gap;   // 太い部分の中央
screw_angles = [0, 90];
pilot_d      = 2.5;       // M3 の下穴。ネジが自分でネジ山を切る

// ---- グリップの溝 ----
flutes  = 12;
flute_d = 2.0;
flute_z0 = 8.0;

// 回転しても軸中心から ring_r - 1.5 mm 以内に収まること
assert(max(flange_r, grip_r, root_r + oring_cs) < ring_r - 1.5, "リングに近すぎる");

mid = (g0 + g1)/2;
pts = [
  [0, 0], [flange_r, 0], [flange_r, g0],
  [root_r, mid - root_w/2], [root_r, mid + root_w/2],
  [flange_r, g1], [flange_r, flange2_end],
  [grip_r, flange2_end], [grip_r, length - 1],
  [grip_r - 1, length], [0, length]
];

difference() {
  rotate_extrude() polygon(pts);
  // 軸穴
  translate([0, 0, -0.1]) cylinder(d = bore_d, h = bore_depth + 0.1);
  // 止めネジの下穴
  for (a = screw_angles)
    rotate([0, 0, a]) translate([0, 0, screw_z]) rotate([0, 90, 0])
      cylinder(d = pilot_d, h = grip_r + 1, $fn = 32);
  // グリップの浅い溝 (止めネジの角度を避けて 15° ずらす)
  for (i = [0 : flutes - 1])
    rotate([0, 0, 360/flutes*i + 15]) translate([grip_r + 0.3, 0, flute_z0])
      cylinder(d = flute_d, h = length - 2 - flute_z0, $fn = 24);
}

echo(str("ベルト込みの最大半径 ", max(flange_r, root_r + oring_cs),
         " mm, リングとの隙間 ", ring_r - max(flange_r, root_r + oring_cs), " mm"));
