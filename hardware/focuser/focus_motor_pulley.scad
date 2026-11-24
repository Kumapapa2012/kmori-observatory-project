// フォーカス電動化: 1218 ウォームギアモーター (Akozon 1218GEN20) の出力軸用の小プーリー。2026-11-22。
// レンダリング未確認。軸の寸法は、ユーザーが提供した図面 (Ø3 の D カット、対辺 2.5、突き出し 8) による。
// 単位 mm。z=0 が軸の先端側、+z がモーター側。
// 取り付け: 軸の先端を、セル面から z=1.9 にそろえる (ベルトの面 z=4.3 = 溝の中心 + 1.9)。
//   すると、モーターの面 (軸が出る面) は z=9.9 になる。プーリーの長さは 7.6 で、面との隙間は約 0.4。
// ハブ (focus_hub.scad) の中心円は約 Ø18.3、ここは約 Ø7.2 (O リング線径 1.5)。減速比は約 1:2.5。
// 刷るときは層を細かく (0.1 mm 前後)。刷りにくければ、金属製の小プーリー (D カット Ø3 用) に替える。

$fn = 96;

shaft_d     = 3.0;
flat_across = 2.5;              // D カットの対辺
shaft_len   = 8.0;              // 面からの突き出し
bore_d      = shaft_d + 0.15;
flat_x      = flat_across - shaft_d/2 + 0.05;   // D カットの平面の位置 (+x 側。軸中心から)

root_r   = 2.9;                 // V 溝の底 Ø5.8。底の肉厚 = 2.9 - 1.575 = 1.3
flange_r = root_r + 1.5;
hub_r    = 5.0;
length   = shaft_len - 0.4;     // 7.6
// 溝は幅 3.2 (上端)、底の幅 0.8。フランジ 0.8 + 溝 3.2 + フランジ 0.8、残りがハブ
g_in   = 0.8;
g_out  = g_in + 3.2;
f_end  = g_out + 0.8;
root_w = 0.8;
mid    = (g_in + g_out)/2;      // 溝の中心 = 2.4
screw_z = (f_end + length)/2;   // ハブの中央
pilot_d = 1.6;                  // M2 止めネジの下穴。D カットの平面へ向ける (+x)

pts = [
  [0, 0], [flange_r, 0], [flange_r, g_in],
  [root_r, mid - root_w/2], [root_r, mid + root_w/2],
  [flange_r, g_out], [flange_r, f_end], [hub_r, f_end], [hub_r, length], [0, length]
];

difference() {
  rotate_extrude() polygon(pts);
  translate([0, 0, -0.1]) linear_extrude(length + 0.2)
    intersection() { circle(d = bore_d); translate([-5, -5]) square([5 + flat_x, 10]); }
  translate([0, 0, screw_z]) rotate([0, 90, 0]) cylinder(d = pilot_d, h = hub_r + 1, $fn = 32);
}

echo(str("溝の中心 z=", mid, ", 先端を z=", 4.3 - mid, " に置く, モーター面 z=", 4.3 - mid + shaft_len));
